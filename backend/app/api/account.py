"""
Account endpoints.

Lets a customer check what their key is worth without spending anything.
"""

from flask import g, jsonify, request

from . import account_bp
from ..models.access_key import (
    PLANS, TOPUP_PACKS, AccessKeyManager, SubscriptionStatus,
)
from ..services import stripe_billing
from ..utils.api_response import error_response
from ..utils.billing import PRICES, require_access_key
from ..utils.logger import get_logger

logger = get_logger('spidernet.api.account')


@account_bp.route('/me', methods=['GET'])
@require_access_key(cost=0)
def whoami():
    """Balance and plan for the presented key. Free to call."""
    return jsonify({
        "success": True,
        "data": g.access_key.to_public_dict(),
    })


@account_bp.route('/pricing', methods=['GET'])
def pricing():
    """What each step costs, in credits. Public - no key needed."""
    return jsonify({
        "success": True,
        "data": {
            "currency": "credits",
            "prices": PRICES,
            "estimated_run_total": (
                PRICES["ontology_generate"]
                + PRICES["graph_build"]
                + PRICES["simulation_prepare"]
                + PRICES["profile_generate"]
                + PRICES["simulation_start"]
                + PRICES["report_generate"]
            ),
        },
    })


@account_bp.route('/plans', methods=['GET'])
def plans():
    """Subscriptions and top-up packs on offer. Public - no key needed."""
    return jsonify({
        "success": True,
        "data": {
            "plans": [
                {"id": name, **details} for name, details in PLANS.items()
            ],
            "topups": [
                {"id": name, **details} for name, details in TOPUP_PACKS.items()
            ],
            "payments_enabled": stripe_billing.is_configured(),
        },
    })


@account_bp.route('/ledger', methods=['GET'])
@require_access_key(cost=0)
def ledger():
    """Every credit movement on this key. Free to read."""
    return jsonify({
        "success": True,
        "data": AccessKeyManager.ledger(g.access_key.public_id, limit=200),
    })


@account_bp.route('/checkout/subscription', methods=['POST'])
@require_access_key(cost=0)
def checkout_subscription():
    """Start paying for a monthly plan."""
    data = request.get_json(silent=True) or {}
    plan = data.get('plan')
    if not plan:
        return error_response("Which plan? Send a plan id.", 400)

    try:
        return jsonify({
            "success": True,
            "data": stripe_billing.create_subscription_checkout(
                g.access_key.public_id, plan
            ),
        })
    except stripe_billing.StripeNotConfigured as e:
        return error_response(str(e), 503)
    except ValueError as e:
        return error_response(str(e), 400)


@account_bp.route('/checkout/topup', methods=['POST'])
@require_access_key(cost=0)
def checkout_topup():
    """Buy a pack of credits that never expire."""
    data = request.get_json(silent=True) or {}
    pack = data.get('pack')
    if not pack:
        return error_response("Which pack? Send a pack id.", 400)

    try:
        return jsonify({
            "success": True,
            "data": stripe_billing.create_topup_checkout(
                g.access_key.public_id, pack
            ),
        })
    except stripe_billing.StripeNotConfigured as e:
        return error_response(str(e), 503)
    except ValueError as e:
        return error_response(str(e), 400)


@account_bp.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """
    Where payments actually become credits.

    Deliberately not behind require_access_key: Stripe has no key of ours. The
    signature is the authentication, and nothing is read from the body before
    it has been checked.
    """
    try:
        event = stripe_billing.verify_event(
            request.get_data(), request.headers.get('Stripe-Signature')
        )
    except stripe_billing.WebhookRejected as e:
        logger.warning(f"Rejected a webhook: {e}")
        # 400 so Stripe stops retrying something that will never verify.
        return error_response("Could not verify that request.", 400)

    try:
        outcome, public_id = stripe_billing.handle_event(event)
    except stripe_billing.WebhookRejected as e:
        logger.error(f"Verified webhook we could not act on: {e}")
        return error_response(str(e), 400)
    except Exception as e:
        # 500 makes Stripe retry, which is what we want for a transient fault:
        # the customer has paid and must end up with their credits.
        logger.error(f"Failed to fulfil {event.get('type')}: {e}")
        return error_response("Could not fulfil that yet.", 500)

    logger.info(f"Webhook {event.get('type')}: {outcome} ({public_id})")
    return jsonify({"success": True, "data": {"outcome": outcome}})
