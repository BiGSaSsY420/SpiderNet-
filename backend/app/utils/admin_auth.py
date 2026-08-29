"""
Operator authentication.

The admin surface sees every customer, every balance and every dollar, so it is
gated separately from the customer paywall. A customer key must never reach it,
however many credits it has.

Two rules that matter more than the rest:

- Fail closed. With no SPIDERNET_ADMIN_TOKEN configured the console is off,
  not open. A missing environment variable is the most likely way this gets
  deployed wrong, and it must fail in the safe direction.
- The token is compared in constant time and required to be long. A short
  admin token on a public endpoint is a matter of time.
"""

import functools
import hmac
import os
from typing import Callable, Optional

from flask import g, request

from .api_response import error_response
from .logger import get_logger

logger = get_logger('spidernet.admin')

HEADER = "X-SpiderNet-Admin"

# Short enough to guess is not a secret. 32 characters of the token generated
# by `python -c "import secrets; print(secrets.token_urlsafe(32))"` is 43.
MIN_TOKEN_LENGTH = 32


def configured_token() -> Optional[str]:
    token = os.environ.get("SPIDERNET_ADMIN_TOKEN") or ""
    return token if len(token) >= MIN_TOKEN_LENGTH else None


def is_enabled() -> bool:
    return configured_token() is not None


def _presented() -> Optional[str]:
    header = request.headers.get(HEADER)
    if header:
        return header.strip()
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def require_admin(view: Callable) -> Callable:
    """Gate an endpoint behind the operator token."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        expected = configured_token()

        if expected is None:
            configured = os.environ.get("SPIDERNET_ADMIN_TOKEN")
            if configured:
                logger.error(
                    "SPIDERNET_ADMIN_TOKEN is set but shorter than "
                    f"{MIN_TOKEN_LENGTH} characters, so the console stays off."
                )
            # Same response either way: an attacker learns nothing about
            # whether an admin console exists here at all.
            return error_response("Not found.", 404)

        presented = _presented()
        if not presented or not hmac.compare_digest(presented, expected):
            logger.warning(
                f"Refused an admin request from {request.remote_addr} "
                f"to {request.path}"
            )
            return error_response("Not found.", 404)

        g.is_admin = True
        return view(*args, **kwargs)

    wrapper.__spidernet_admin__ = True
    return wrapper
