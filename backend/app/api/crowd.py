"""
Crowd endpoints.

Building a world is expensive and slow. Asking one is cheap and fast. These
endpoints expose the cheap half on its own, so a customer can pay once for a
population and then question it as often as they like.
"""

from flask import g, jsonify, request

from . import crowd_bp
from ..models.crowd import CrowdManager, CrowdVisibility
from ..services.simulation_manager import SimulationManager
from ..utils.api_response import error_response
from ..utils.billing import (
    PRICES, assert_owner, current_key_id, require_access_key,
)
from ..utils.logger import get_logger

logger = get_logger('spidernet.api.crowd')


@crowd_bp.route('', methods=['GET'])
@require_access_key(cost=0)
def list_crowds():
    """Crowds you own, plus the shared library. Free to browse."""
    crowds = CrowdManager.list_for(current_key_id())
    return jsonify({
        "success": True,
        "data": [c.to_dict() for c in crowds],
        "count": len(crowds),
    })


@crowd_bp.route('/<crowd_id>', methods=['GET'])
@require_access_key(cost=0)
def get_crowd(crowd_id: str):
    crowd = CrowdManager.get(crowd_id)
    if crowd is None:
        return error_response("No such crowd.", 404)
    if crowd.visibility != CrowdVisibility.LIBRARY:
        assert_owner(crowd.owner_key_id)
    return jsonify({"success": True, "data": crowd.to_dict()})


@crowd_bp.route('/from-simulation', methods=['POST'])
@require_access_key(cost=0)
def capture_crowd():
    """
    Save the people from a finished run so they can be asked things later.

    Free: the customer already paid to create them.
    """
    data = request.get_json(silent=True) or {}
    simulation_id = data.get('simulation_id')
    name = (data.get('name') or '').strip()

    if not simulation_id:
        return error_response("Which run? Send a simulation_id.", 400)
    if not name:
        return error_response("Give the crowd a name so you can find it again.", 400)

    manager = SimulationManager()
    state = manager.get_simulation(simulation_id)
    if state is None:
        return error_response("No such run.", 404)

    # You may only capture people from a run you own.
    assert_owner(getattr(state, 'owner_key_id', None))

    platform = data.get('platform', 'reddit')
    people = manager.get_profiles(simulation_id, platform=platform)
    if not people:
        return error_response(
            "That run has no people in it yet. Let it finish building first.", 400
        )

    crowd = CrowdManager.create(
        name=name,
        people=people,
        owner_key_id=current_key_id(),
        description=(data.get('description') or '').strip(),
        source_simulation_id=simulation_id,
        graph_id=getattr(state, 'graph_id', None),
        tags=data.get('tags') or [],
    )
    return jsonify({"success": True, "data": crowd.to_dict()}), 201


@crowd_bp.route('/<crowd_id>/ask', methods=['POST'])
@require_access_key(cost=PRICES['crowd_ask'])
def ask_crowd(crowd_id: str):
    """
    Ask the crowd a question and get everyone's answer.

    This is the cheap, fast path the whole product hangs on: seconds and a
    couple of credits, against forty minutes and a hundred and ninety for a
    full run.
    """
    crowd = CrowdManager.get(crowd_id)
    if crowd is None:
        return error_response("No such crowd.", 404)
    if crowd.visibility != CrowdVisibility.LIBRARY:
        assert_owner(crowd.owner_key_id)

    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return error_response("What would you like to ask them?", 400)

    try:
        sample_size = int(data.get('sample_size', 25))
    except (TypeError, ValueError):
        return error_response("sample_size must be a whole number.", 400)
    if sample_size < 1:
        return error_response("Ask at least one person.", 400)

    result = CrowdManager.poll(crowd_id, question, sample_size=sample_size)

    if result["answered"] == 0:
        # require_access_key refunds on any error status, so returning one here
        # is enough - the customer is not charged for silence.
        return error_response(
            "Nobody managed to answer that. Please try again.", 502
        )

    return jsonify({"success": True, "data": result})


@crowd_bp.route('/<crowd_id>', methods=['DELETE'])
@require_access_key(cost=0)
def delete_crowd(crowd_id: str):
    crowd = CrowdManager.get(crowd_id)
    if crowd is None:
        return error_response("No such crowd.", 404)
    assert_owner(crowd.owner_key_id)

    CrowdManager.delete(crowd_id)
    return jsonify({"success": True, "message": f"Deleted {crowd.name}."})
