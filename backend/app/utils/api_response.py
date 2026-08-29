"""
统一的 API 响应封装

所有接口返回同一种信封：
    成功  {"success": true,  "data": ...}
    失败  {"success": false, "error": "..."}

错误响应默认不包含堆栈。堆栈会写进服务端日志，只有显式开启 DEBUG 时才回传给
客户端 —— 生产环境把 traceback 发给调用方会泄露文件路径与内部结构。
"""

import traceback
from typing import Any, Optional, Tuple

from flask import current_app, jsonify

from .logger import get_logger
from .safe_path import UnsafeIdentifierError

logger = get_logger('mirofish.api')


def _include_traceback() -> bool:
    try:
        return bool(current_app.config.get('DEBUG', False))
    except RuntimeError:          # 不在请求上下文中
        return False


def success_response(data: Any = None, **extra: Any) -> Tuple[Any, int]:
    payload = {"success": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload), 200


def _infer_status(error: Any) -> int:
    """为已知异常类型选择合适的状态码。"""
    if isinstance(error, UnsafeIdentifierError):
        # 不区分"非法"与"不存在"，避免泄露存储布局
        return 404
    if type(error).__name__ == "NotYourResource":
        # 404 而非 403：不要泄露"该资源确实存在，只是不属于你"
        return 404
    return 500


def error_response(
    error: Any,
    status: Optional[int] = None,
    log_context: Optional[str] = None,
) -> Tuple[Any, int]:
    """
    构造错误响应，并把完整堆栈记录到服务端日志。

    各路由内部普遍写有 `except Exception` 兜底，会先于 Flask 的 errorhandler
    捕获异常，因此这里也要能识别已知异常类型并给出正确状态码。

    Args:
        error: 异常对象或错误信息
        status: HTTP 状态码；为 None 时按异常类型推断
        log_context: 日志中附加的上下文说明
    """
    if status is None:
        status = _infer_status(error)

    message = str(error)
    if isinstance(error, UnsafeIdentifierError) or type(error).__name__ == "NotYourResource":
        message = "资源不存在"

    payload = {"success": False, "error": message}

    if isinstance(error, BaseException):
        logger.error(
            f"{log_context or 'API 错误'}: {message}",
            exc_info=(type(error), error, error.__traceback__),
        )
        if _include_traceback():
            payload["traceback"] = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
    else:
        logger.error(f"{log_context or 'API 错误'}: {message}")

    return jsonify(payload), status


def register_error_handlers(app) -> None:
    """把常见异常映射为规范的 JSON 响应，而不是 500 + 堆栈。"""

    from .billing import NotYourResource

    @app.errorhandler(NotYourResource)
    def _not_your_resource(e):
        return error_response("资源不存在", 404)

    @app.errorhandler(UnsafeIdentifierError)
    def _unsafe_identifier(e):
        # 不区分"非法"与"不存在"，避免泄露存储布局
        logger.warning(f"拒绝非法标识符: {e}")
        return error_response("资源不存在", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(getattr(e, 'description', '请求格式错误'), 400)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("资源不存在", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("请求方法不被支持", 405)

    @app.errorhandler(413)
    def _payload_too_large(e):
        return error_response("上传内容超出大小限制", 413)

    @app.errorhandler(Exception)
    def _unhandled(e):
        # 不写死 500：让 _infer_status 决定（如 NotYourResource -> 404）
        return error_response(e, log_context="未处理的异常")
