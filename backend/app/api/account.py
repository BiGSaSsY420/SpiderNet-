"""
Account endpoints.

Lets a customer check what their key is worth without spending anything.
"""

from flask import g, jsonify

from . import account_bp
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
