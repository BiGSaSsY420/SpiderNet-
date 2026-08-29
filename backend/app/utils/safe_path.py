"""
存储路径安全

project_id / simulation_id / report_id 等标识符直接来自 URL 路径，
之后会被拼进文件系统路径并交给 rmtree / makedirs / open。
未经校验的标识符可以带上 `..` 逃出存储根目录。

所有标识符均由服务端生成，形如 `proj_2b7f1a9c4d3e`，因此可以用一个
很严格的白名单来校验。
"""

import os
import re
from typing import Optional

# 服务端生成的 ID：前缀 + 十六进制。放宽到 [A-Za-z0-9_-] 以兼容历史数据。
_SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


class UnsafeIdentifierError(ValueError):
    """标识符无法安全地用作路径片段。"""


def validate_storage_id(value: Optional[str], kind: str = "标识符") -> str:
    """
    校验一个将被用作路径片段的标识符。

    Args:
        value: 待校验的标识符
        kind: 出现在错误信息中的名称（如 "project_id"）

    Returns:
        原样返回该标识符

    Raises:
        UnsafeIdentifierError: 标识符为空、类型错误或包含路径分隔符
    """
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise UnsafeIdentifierError(f"非法的{kind}: {value!r}")
    return value


def safe_join(root: str, *parts: str) -> str:
    """
    在 root 下拼接路径，并确认结果没有逃出 root。

    每个片段都会先经过 validate_storage_id 校验（最后一段允许带扩展名）。

    Raises:
        UnsafeIdentifierError: 任一片段非法，或结果落在 root 之外
    """
    for part in parts:
        stem = part
        # 允许 project.json / extracted_text.txt 这类文件名
        if '.' in part:
            stem = part.rsplit('.', 1)[0]
        validate_storage_id(stem, "路径片段")

    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, *parts))

    if target != root_abs and not target.startswith(root_abs + os.sep):
        raise UnsafeIdentifierError(f"路径逃出了存储根目录: {target!r}")

    return target
