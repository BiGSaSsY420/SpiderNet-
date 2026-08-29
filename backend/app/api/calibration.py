"""
Calibration endpoints.

Recording predictions and outcomes is free. Charging for honesty about your own
accuracy would be a strange incentive, and the record is worth more to us than
the credits.
"""

from flask import jsonify, request

from . import calibration_bp
from ..models.calibration import (
    AlreadyResolved, CalibrationStore, PredictionStatus,
)
from ..utils.api_response import error_response
from ..utils.billing import assert_owner, current_key_id, require_access_key
from ..utils.logger import get_logger

logger = get_logger('spidernet.api.calibration')


@calibration_bp.route('/predictions', methods=['POST'])
@require_access_key(cost=0)
def record_prediction():
    """Write down a claim before reality is known."""
    data = request.get_json(silent=True) or {}
    try:
        prediction = CalibrationStore.record(
            question=data.get('question', ''),
            claim=data.get('claim', ''),
            probability=data.get('probability', None),
            owner_key_id=current_key_id(),
            crowd_id=data.get('crowd_id'),
            simulation_id=data.get('simulation_id'),
            resolve_by=data.get('resolve_by'),
            tags=data.get('tags') or [],
        )
    except (ValueError, TypeError) as e:
        return error_response(str(e), 400)

    return jsonify({"success": True, "data": prediction.to_dict()}), 201


@calibration_bp.route('/predictions', methods=['GET'])
@require_access_key(cost=0)
def list_predictions():
    raw_status = request.args.get('status')
    status = None
    if raw_status:
        try:
            status = PredictionStatus(raw_status)
        except ValueError:
            return error_response(
                f"status must be 'open' or 'resolved', got {raw_status!r}", 400
            )

    predictions = CalibrationStore.list_for(current_key_id(), status=status)
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in predictions],
        "count": len(predictions),
    })


@calibration_bp.route('/predictions/<prediction_id>/outcome', methods=['POST'])
@require_access_key(cost=0)
def resolve_prediction(prediction_id: str):
    """Record what actually happened."""
    prediction = CalibrationStore.get(prediction_id)
    if prediction is None:
        return error_response("No such prediction.", 404)
    assert_owner(prediction.owner_key_id)

    data = request.get_json(silent=True) or {}
    if 'outcome' not in data:
        return error_response(
            "Did it happen? Send outcome as true or false.", 400
        )
    if not isinstance(data['outcome'], bool):
        return error_response("outcome must be true or false.", 400)

    try:
        resolved = CalibrationStore.resolve(
            prediction_id, data['outcome'], note=data.get('note', '')
        )
    except AlreadyResolved as e:
        return error_response(str(e), 409)

    return jsonify({"success": True, "data": resolved.to_dict()})


@calibration_bp.route('/scorecard', methods=['GET'])
@require_access_key(cost=0)
def scorecard():
    """How good the predictions have actually been."""
    return jsonify({
        "success": True,
        "data": CalibrationStore.scorecard(current_key_id()),
    })
