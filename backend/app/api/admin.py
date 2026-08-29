"""
Operator console.

Everything here sees across customers, so all of it is behind the admin token
and none of it is reachable with a customer key. Key hashes are never returned:
the console is for running the business, not for impersonating people in it.
"""

from flask import jsonify, request

from . import admin_bp
from ..models.access_key import (
    PLANS, TOPUP_PACKS, AccessKeyManager, KeyStatus, SubscriptionStatus,
)
from ..models.calibration import CalibrationStore
from ..models.crowd import CrowdManager
from ..services import stripe_billing
from ..utils.admin_auth import is_enabled, require_admin
from ..utils.api_response import error_response
from ..utils.logger import get_logger

logger = get_logger('spidernet.api.admin')


@admin_bp.route('/overview', methods=['GET'])
@require_admin
def overview():
    """Revenue, customers and what is owed, in one call."""
    summary = AccessKeyManager.business_summary()
    return jsonify({
        "success": True,
        "data": {
            **summary,
            "payments_enabled": stripe_billing.is_configured(),
            "recent_activity": AccessKeyManager.recent_activity(limit=25),
        },
    })


@admin_bp.route('/customers', methods=['GET'])
@require_admin
def customers():
    """Every key, with balances and usage."""
    keys = AccessKeyManager.all_keys()
    return jsonify({
        "success": True,
        "data": [k.to_public_dict() for k in keys],
        "count": len(keys),
    })


@admin_bp.route('/customers/<public_id>', methods=['GET'])
@require_admin
def customer(public_id: str):
    record = AccessKeyManager.get(public_id)
    if record is None:
        return error_response("No such customer.", 404)

    return jsonify({
        "success": True,
        "data": {
            **record.to_public_dict(),
            "ledger": AccessKeyManager.ledger(public_id, limit=200),
            "crowds": [
                c.to_dict() for c in CrowdManager.list_for(public_id)
                if c.owner_key_id == public_id
            ],
            "scorecard": CalibrationStore.scorecard(public_id),
        },
    })


@admin_bp.route('/customers', methods=['POST'])
@require_admin
def create_customer():
    """Issue a key by hand — a trial, a comp, a customer who paid by invoice."""
    data = request.get_json(silent=True) or {}
    label = (data.get('label') or '').strip()
    if not label:
        return error_response("Who is it for? Send a label.", 400)

    plan = data.get('plan', 'trial')
    if plan not in PLANS:
        return error_response(f"Unknown plan: {plan}", 400)

    try:
        credits = int(data.get('credits', 0) or 0)
    except (TypeError, ValueError):
        return error_response("credits must be a whole number.", 400)
    if credits < 0:
        return error_response("credits cannot be negative.", 400)

    issued = AccessKeyManager.issue(
        label=label, plan=plan, credits=credits,
        subscribe=bool(data.get('subscribe')),
        environment=data.get('environment', 'live'),
    )
    logger.info(f"Operator issued a key to {label} on {plan}")
    # The plaintext appears here and nowhere else, ever.
    return jsonify({"success": True, "data": issued}), 201


@admin_bp.route('/customers/<public_id>/credits', methods=['POST'])
@require_admin
def grant_credits(public_id: str):
    """Add credits by hand: a goodwill gesture, or a payment taken elsewhere."""
    if AccessKeyManager.get(public_id) is None:
        return error_response("No such customer.", 404)

    data = request.get_json(silent=True) or {}
    try:
        credits = int(data.get('credits', 0))
    except (TypeError, ValueError):
        return error_response("credits must be a whole number.", 400)
    if credits <= 0:
        return error_response("Grant a positive number of credits.", 400)

    reason = (data.get('reason') or 'granted by operator').strip()
    record = AccessKeyManager.add_topup(public_id, credits, reason=reason)
    return jsonify({"success": True, "data": record.to_public_dict()})


@admin_bp.route('/customers/<public_id>/plan', methods=['POST'])
@require_admin
def set_plan(public_id: str):
    """Move a customer onto a plan without going through Stripe."""
    if AccessKeyManager.get(public_id) is None:
        return error_response("No such customer.", 404)

    data = request.get_json(silent=True) or {}
    plan = data.get('plan')
    if plan not in PLANS:
        return error_response(f"Unknown plan: {plan}", 400)

    record = AccessKeyManager.start_subscription(public_id, plan)
    return jsonify({"success": True, "data": record.to_public_dict()})


@admin_bp.route('/customers/<public_id>/revoke', methods=['POST'])
@require_admin
def revoke(public_id: str):
    if AccessKeyManager.get(public_id) is None:
        return error_response("No such customer.", 404)
    record = AccessKeyManager.revoke(public_id)
    logger.info(f"Operator revoked {public_id}")
    return jsonify({"success": True, "data": record.to_public_dict()})


@admin_bp.route('/crowds', methods=['GET'])
@require_admin
def all_crowds():
    """Every crowd, including private ones — for spotting library candidates."""
    crowds = CrowdManager.all_crowds()
    return jsonify({
        "success": True,
        "data": sorted(
            [c.to_dict() for c in crowds],
            key=lambda c: c["poll_count"], reverse=True,
        ),
    })


@admin_bp.route('/status', methods=['GET'])
@require_admin
def status():
    """What is switched on, so a misconfigured deployment is visible."""
    return jsonify({
        "success": True,
        "data": {
            "admin_console": is_enabled(),
            "payments_enabled": stripe_billing.is_configured(),
            "plans": list(PLANS),
            "topup_packs": list(TOPUP_PACKS),
        },
    })
