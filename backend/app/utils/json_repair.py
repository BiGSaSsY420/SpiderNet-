"""
LLM JSON 输出修复

LLM 返回的 JSON 有三种常见破损方式：
1. 被 markdown 代码块包裹（```json ... ```）
2. 因为 max_tokens 被截断（结构没有闭合）
3. 前后混有解释性文字

这里用一个感知字符串状态的扫描器处理前两种：括号计数只在字符串字面量
之外进行，因此 `{"bio": "包含 {括号} 的文本"}` 不会被误判。

契约：
- 完整合法的 JSON 原样返回，绝不改动。
- 截断的 JSON 只保留可信部分：结尾未被分隔符终止的标量（数字 / true / null）
  会被丢弃，因为截断的 123 与完整的 12 无法区分。
- 截断的字符串保留已生成的前缀（调用方能看出它戛然而止）。
- 无法安全修复时返回 None，绝不返回"能解析但值已被悄悄改错"的结果。
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# ```json ... ``` 包裹
_FENCE_OPEN = re.compile(r'^\s*```(?:json)?\s*\n?', re.IGNORECASE)
_FENCE_CLOSE = re.compile(r'\n?\s*```\s*$')

# 推理模型（MiniMax / GLM 等）会输出思考过程
_THINK_BLOCK = re.compile(r'<think>[\s\S]*?</think>', re.IGNORECASE)


def strip_wrappers(text: str) -> str:
    """移除 <think> 块与 markdown 代码围栏。"""
    if not text:
        return ""
    text = _THINK_BLOCK.sub('', text)
    # 未闭合的 <think>：丢弃其后所有内容
    open_think = re.search(r'<think>', text, re.IGNORECASE)
    if open_think:
        text = text[:open_think.start()]
    text = text.strip()
    text = _FENCE_OPEN.sub('', text)
    text = _FENCE_CLOSE.sub('', text)
    return text.strip()


def _scan(s: str) -> Tuple[List[str], bool, bool, int]:
    """
    扫描一遍 JSON 文本，返回：
      (未闭合的闭合符栈, 结尾是否处于字符串内, 结尾是否处于转义中,
       最后一个"完整元素"结束的位置)

    最后一项用于在无法闭合当前值时回退到上一个完整元素。
    """
    closers: List[str] = []
    # 每层容器中，当前读取的是 key 还是 value
    expecting: List[str] = []
    in_string = False
    escaped = False
    safe = 0

    def in_key_position() -> bool:
        return bool(closers) and closers[-1] == '}' and expecting[-1] == 'key'

    for i, ch in enumerate(s):
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
                if not in_key_position():
                    safe = i + 1
            continue

        if ch == '"':
            in_string = True
        elif ch == '{':
            closers.append('}')
            expecting.append('key')
            safe = i + 1
        elif ch == '[':
            closers.append(']')
            expecting.append('value')
            safe = i + 1
        elif ch in '}]':
            if closers:
                closers.pop()
                expecting.pop()
            safe = i + 1
        elif ch == ':':
            if expecting:
                expecting[-1] = 'value'
        elif ch == ',':
            if expecting and closers and closers[-1] == '}':
                expecting[-1] = 'key'
            # 截断点取逗号之前
            safe = i
        # 标量（数字 / true / false / null）不推进 safe：
        # 截断的 123 与完整的 12 无法区分，只有遇到分隔符才能确认其结束。

    return closers, in_string, escaped, safe


def _candidates(s: str) -> List[str]:
    """生成按优先级排列的修复候选。"""
    out = [s]
    closers, in_string, escaped, safe = _scan(s)

    stripped = s.rstrip()
    ends_mid_scalar = (
        not in_string
        and bool(stripped)
        and stripped[-1] not in '"}],:{['
    )

    # 策略 A：闭合当前未结束的字符串与容器，尽量保留已生成的内容。
    # 若文本结束在一个未被分隔符终止的标量上则跳过 —— 那个值不可信。
    if not ends_mid_scalar:
        partial = s
        if escaped:
            partial = partial[:-1]      # 丢掉悬空的反斜杠
        if in_string:
            partial += '"'
        if closers:
            partial += ''.join(reversed(closers))
        if partial != s:
            out.append(partial)

    # 策略 B：回退到最后一个完整元素，丢弃残缺的尾巴
    if 0 < safe <= len(s):
        trimmed = s[:safe].rstrip().rstrip(',')
        t_closers, t_in_string, _, _ = _scan(trimmed)
        if not t_in_string:
            out.append(trimmed + ''.join(reversed(t_closers)))

    return out


def repair_json(text: str) -> Optional[Dict[str, Any]]:
    """
    尽力将 LLM 输出解析为 JSON 对象。

    Args:
        text: LLM 原始输出

    Returns:
        解析后的 dict；无法安全修复时返回 None
    """
    if not text or not text.strip():
        return None

    cleaned = strip_wrappers(text)
    if not cleaned:
        return None

    # 1. 直接解析
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    # 2. 从混杂文本中截出对象部分
    start = cleaned.find('{')
    if start == -1:
        return None
    body = cleaned[start:]

    # 3. 依次尝试修复候选
    for candidate in _candidates(body):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    # 4. 最后手段：移除字符串外的控制字符后重试
    sanitized = _strip_control_chars(body)
    if sanitized != body:
        for candidate in _candidates(sanitized):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    return None


def _strip_control_chars(s: str) -> str:
    """把字符串字面量内部的裸控制字符替换为空格（字面量之外的原样保留）。"""
    out = []
    in_string = False
    escaped = False
    for ch in s:
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            if in_string and ord(ch) < 0x20:
                out.append(' ')
                continue
        elif ch == '"':
            in_string = True
        out.append(ch)
    return ''.join(out)
