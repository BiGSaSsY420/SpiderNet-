"""
Access control and pricing for paid endpoints.

Every operation that spends real money — an LLM call, a graph build, a
simulation run — is priced in credits and gated behind a customer's access key.
Read-only endpoints (polling a task, fetching a finished report) are free, so a
customer is never charged for watching work they already paid for.

Usage:

    @graph_bp.route('/build', methods=['POST'])
    @require_access_key(cost=PRICES['graph_build'])
    def build_graph():
        ...

The charge is taken up front. If the handler raises, the credits are returned,
so a failure on our side never costs the customer.
"""

import functools
from typing import Callable, Optional

from flask import g, request

from ..models.access_key import AccessKeyManager, InsufficientCredits
from .api_response import error_response
from .logger import get_logger

logger = get_logger('spidernet.billing')

# Credit price per operation.
#
# One credit is the unit we sell. These are anchored to the roughly $5 that a
# full run costs us in LLM spend, spread across the stages that actually burn
# tokens, then rounded to numbers a customer can reason about.
PRICES = {
    "ontology_generate": 10,    # one LLM pass over the uploaded documents
    "graph_build": 40,          # chunked extraction, the heaviest ingest stage
    "profile_generate": 25,     # one LLM call per simulated person
    "simulation_prepare": 15,   # config generation plus environment setup
    "simulation_start": 60,     # the run itself, scales with rounds
    "report_generate": 40,      # multi-tool agent pass over the finished world
    "report_chat": 2,           # a single follow-up question
    "interview": 2,             # asking one simulated person one question
    "interview_batch": 10,
}

HEADER = "X-SpiderNet-Key"


def _presented_key() -> Optional[str]:
    """
    Read the key from the request.

    Accepts an Authorization: Bearer header, our own header, or a query
    parameter. The query parameter exists because EventSource cannot set
    headers; it is the least private option since it lands in access logs.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    header = request.headers.get(HEADER)
    if header:
        return header.strip()

    return request.args.get("access_key")


def require_access_key(cost: int = 0):
    """
    Gate an endpoint behind a valid key, charging `cost` credits.

    On success the key record is available as `g.access_key`, and the amount
    charged as `g.charged_credits`, so a handler can refund itself if it
    decides not to do the work after all.
    """
    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            presented = _presented_key()

            if not presented:
                return error_response(
                    "This endpoint needs an access key. "
                    "Send it as 'Authorization: Bearer <key>'.",
                    401,
                )

            record = AccessKeyManager.verify(presented)
            if record is None:
                # One message for malformed, unknown and revoked alike, so the
                # response cannot be used to probe which keys exist.
                return error_response("That access key is not valid.", 401)

            g.access_key = record
            g.charged_credits = 0

            if cost > 0:
                try:
                    record = AccessKeyManager.charge(
                        record.public_id, cost, reason=view.__name__
                    )
                except InsufficientCredits as e:
                    return error_response(
                        f"Not enough credits. This step costs {e.required} and "
                        f"you have {e.remaining}. Add credits to keep going.",
                        402,
                    )
                except KeyError:
                    return error_response("That access key is not valid.", 401)

                g.access_key = record
                g.charged_credits = cost

            try:
                return view(*args, **kwargs)
            except Exception:
                # We took the money before doing the work; give it back if the
                # work never happened.
                if g.get("charged_credits"):
                    try:
                        AccessKeyManager.refund(
                            record.public_id,
                            g.charged_credits,
                            reason=f"{view.__name__} failed",
                        )
                    except Exception as refund_error:
                        logger.error(
                            f"Could not refund {g.charged_credits} credits to "
                            f"{record.public_id}: {refund_error}"
                        )
                raise

        # Lets the test suite (and any audit) see which endpoints are gated
        # and at what price, without calling them.
        wrapper.__spidernet_cost__ = cost
        return wrapper
    return decorator


class NotYourResource(Exception):
    """A valid key asked for something belonging to a different customer."""


def current_key_id() -> Optional[str]:
    """Public id of the key on this request, or None outside a gated route."""
    key = g.get("access_key") if g else None
    return key.public_id if key else None


def assert_owner(owner_key_id: Optional[str]) -> None:
    """
    Confirm the current key owns a resource.

    Records created before ownership existed carry no owner and stay reachable,
    so upgrading does not strand anyone's existing projects.

    Raises:
        NotYourResource: the resource belongs to someone else
    """
    if owner_key_id is None:
        return
    caller = current_key_id()
    if caller is None or caller != owner_key_id:
        logger.warning(
            f"Key {caller or 'anonymous'} was refused a resource owned by {owner_key_id}"
        )
        raise NotYourResource()
