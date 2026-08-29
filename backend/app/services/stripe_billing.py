"""
Stripe: taking the money, and turning it into credits.

Two things are bought here — a subscription, which grants a monthly allowance,
and a top-up pack, which grants credits outright. Both are fulfilled from
webhooks rather than from the browser redirect, because the redirect is under
the customer's control: anyone can open the success URL, and a customer who
closes the tab after paying must still get what they paid for.

Nothing in this module trusts the request body until the Stripe signature has
been checked. An unsigned webhook is an endpoint that hands out free credits to
whoever finds the URL.
"""

import json
import os
from typing import Any, Dict, Optional, Tuple

from ..models.access_key import (
    PLANS, TOPUP_PACKS, AccessKeyManager, SubscriptionStatus,
)
from ..utils.logger import get_logger

logger = get_logger('spidernet.stripe')


class StripeNotConfigured(Exception):
    """Stripe keys are absent, so nothing can be sold."""


class WebhookRejected(Exception):
    """The payload did not come from Stripe, or we could not act on it."""


def _config() -> Dict[str, Optional[str]]:
    return {
        "secret_key": os.environ.get("STRIPE_SECRET_KEY"),
        "webhook_secret": os.environ.get("STRIPE_WEBHOOK_SECRET"),
        "success_url": os.environ.get(
            "STRIPE_SUCCESS_URL", "http://localhost:3000/billing?paid=1"
        ),
        "cancel_url": os.environ.get(
            "STRIPE_CANCEL_URL", "http://localhost:3000/billing"
        ),
    }


def is_configured() -> bool:
    return bool(_config()["secret_key"])


def _client():
    cfg = _config()
    if not cfg["secret_key"]:
        raise StripeNotConfigured(
            "Set STRIPE_SECRET_KEY to sell subscriptions or top-ups."
        )
    import stripe
    stripe.api_key = cfg["secret_key"]
    return stripe


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def create_subscription_checkout(public_id: str, plan: str) -> Dict[str, Any]:
    """
    A Checkout session for a monthly plan.

    The key's public id rides along in metadata and client_reference_id, which
    is how the webhook knows whose balance to credit later.
    """
    if plan not in PLANS:
        raise ValueError(f"Unknown plan: {plan}")
    if PLANS[plan]["price_usd"] <= 0:
        raise ValueError(f"{plan} is free; there is nothing to charge for.")

    stripe = _client()
    cfg = _config()
    details = PLANS[plan]

    session = stripe.checkout.Session.create(
        mode="subscription",
        client_reference_id=public_id,
        metadata={"public_id": public_id, "plan": plan, "kind": "subscription"},
        subscription_data={
            "metadata": {"public_id": public_id, "plan": plan},
        },
        line_items=[{
            "price_data": {
                "currency": "usd",
                "recurring": {"interval": "month"},
                "unit_amount": details["price_usd"] * 100,
                "product_data": {
                    "name": f"SpiderNet {details['label']}",
                    "description": (
                        f"{details['monthly_credits']:,} credits every month"
                    ),
                },
            },
            "quantity": 1,
        }],
        success_url=cfg["success_url"],
        cancel_url=cfg["cancel_url"],
    )
    logger.info(f"Checkout for {public_id}: subscription {plan}")
    return {"checkout_url": session.url, "session_id": session.id}


def create_topup_checkout(public_id: str, pack: str) -> Dict[str, Any]:
    """A Checkout session for a one-off credit pack."""
    if pack not in TOPUP_PACKS:
        raise ValueError(f"Unknown pack: {pack}")

    stripe = _client()
    cfg = _config()
    details = TOPUP_PACKS[pack]

    session = stripe.checkout.Session.create(
        mode="payment",
        client_reference_id=public_id,
        metadata={
            "public_id": public_id,
            "pack": pack,
            "credits": str(details["credits"]),
            "kind": "topup",
        },
        line_items=[{
            "price_data": {
                "currency": "usd",
                "unit_amount": details["price_usd"] * 100,
                "product_data": {
                    "name": f"SpiderNet {details['label']}",
                    "description": "Credits that never expire",
                },
            },
            "quantity": 1,
        }],
        success_url=cfg["success_url"],
        cancel_url=cfg["cancel_url"],
    )
    logger.info(f"Checkout for {public_id}: top-up {pack}")
    return {"checkout_url": session.url, "session_id": session.id}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def verify_event(payload: bytes, signature_header: Optional[str]) -> Dict[str, Any]:
    """
    Confirm a webhook really came from Stripe.

    Raises:
        WebhookRejected: no signature, wrong signature, or replayed too late
    """
    cfg = _config()
    if not cfg["webhook_secret"]:
        raise WebhookRejected(
            "STRIPE_WEBHOOK_SECRET is not set, so webhooks cannot be trusted."
        )
    if not signature_header:
        raise WebhookRejected("Missing Stripe-Signature header.")

    stripe = _client()
    try:
        stripe.Webhook.construct_event(
            payload, signature_header, cfg["webhook_secret"]
        )
    except Exception as e:
        # Covers a bad signature and a timestamp outside the tolerance, which
        # is what stops a captured webhook being replayed for free credits.
        raise WebhookRejected(f"Signature check failed: {e}") from e

    # The signature proved this exact payload came from Stripe, so parse it
    # directly rather than handing callers an SDK object with its own
    # attribute semantics.
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError) as e:
        raise WebhookRejected(f"Signed payload was not JSON: {e}") from e


def _key_for(event_object: Dict[str, Any]) -> Optional[str]:
    """Work out whose key an event belongs to."""
    metadata = event_object.get("metadata") or {}
    public_id = metadata.get("public_id") or event_object.get("client_reference_id")
    if public_id:
        return public_id

    subscription_id = event_object.get("subscription") or event_object.get("id")
    if subscription_id:
        record = AccessKeyManager.find_by_stripe_subscription(subscription_id)
        if record:
            return record.public_id

    customer_id = event_object.get("customer")
    if customer_id:
        record = AccessKeyManager.find_by_stripe_customer(customer_id)
        if record:
            return record.public_id
    return None


def handle_event(event: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """
    Act on a verified Stripe event.

    Returns (what happened, public_id). Unrecognised event types are ignored
    rather than treated as errors — Stripe sends plenty we did not ask for, and
    returning a failure for those makes it retry forever.
    """
    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    public_id = _key_for(obj)

    if event_type == "checkout.session.completed":
        if not public_id:
            raise WebhookRejected("Paid session carries no public_id.")
        metadata = obj.get("metadata") or {}

        if metadata.get("kind") == "topup":
            credits = int(metadata.get("credits", 0))
            if credits <= 0:
                raise WebhookRejected("Top-up session carries no credit amount.")
            AccessKeyManager.add_topup(
                public_id, credits, reason=f"stripe {obj.get('id', '')}"
            )
            return f"added {credits} credits", public_id

        plan = metadata.get("plan")
        if plan:
            AccessKeyManager.start_subscription(
                public_id, plan,
                stripe_customer_id=obj.get("customer"),
                stripe_subscription_id=obj.get("subscription"),
            )
            return f"subscribed to {plan}", public_id

        return "ignored: session was neither a top-up nor a plan", public_id

    if event_type == "invoice.payment_succeeded":
        # Fires on every renewal, including the first. The first is already
        # handled by checkout.session.completed; renew is idempotent in effect
        # because it sets the allowance rather than adding to it.
        if public_id and obj.get("billing_reason") == "subscription_cycle":
            AccessKeyManager.renew_subscription(public_id)
            return "renewed", public_id
        return "ignored: not a renewal", public_id

    if event_type == "invoice.payment_failed":
        if public_id:
            AccessKeyManager.set_subscription_status(
                public_id, SubscriptionStatus.PAST_DUE
            )
            return "marked past due", public_id
        return "ignored: unknown key", None

    if event_type == "customer.subscription.deleted":
        if public_id:
            AccessKeyManager.set_subscription_status(
                public_id, SubscriptionStatus.CANCELED
            )
            return "marked canceled", public_id
        return "ignored: unknown key", None

    return f"ignored: {event_type}", public_id
