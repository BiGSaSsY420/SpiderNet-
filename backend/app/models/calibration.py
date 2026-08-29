"""
Calibration: did the prediction match what actually happened?

Everything else here can be rebuilt by a competitor in a few months. This
cannot: a record of what SpiderNet said would happen, what did happen, and how
far apart they were. It only accumulates by being used, and it is the
difference between "our simulation is accurate" as a claim and as a number.

The design is deliberately boring:

- A Prediction is recorded when a run finishes, with the claim in it.
- An Outcome is recorded later, by a person, when reality is known.
- Scoring is a Brier score over stated probabilities, which is proper: you
  cannot improve it by hedging or by being confidently wrong.

Predictions are immutable once scored. Letting someone edit a prediction after
seeing the outcome would make the whole record worthless, so the store refuses
it rather than trusting callers to behave.
"""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.safe_path import safe_join, validate_storage_id

logger = get_logger('spidernet.calibration')


class PredictionStatus(str, Enum):
    OPEN = "open"          # made, reality not yet known
    RESOLVED = "resolved"  # outcome recorded and scored


@dataclass
class Prediction:
    """One falsifiable claim, with the confidence attached to it."""
    prediction_id: str
    crowd_id: Optional[str]
    simulation_id: Optional[str]
    owner_key_id: Optional[str]
    question: str
    claim: str
    probability: float           # 0..1, what we said the odds were
    created_at: str
    resolve_by: Optional[str] = None
    status: PredictionStatus = PredictionStatus.OPEN
    outcome: Optional[bool] = None
    outcome_note: str = ""
    resolved_at: Optional[str] = None
    brier: Optional[float] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = (
            self.status.value if isinstance(self.status, PredictionStatus)
            else self.status
        )
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Prediction':
        return cls(
            prediction_id=data["prediction_id"],
            crowd_id=data.get("crowd_id"),
            simulation_id=data.get("simulation_id"),
            owner_key_id=data.get("owner_key_id"),
            question=data.get("question", ""),
            claim=data.get("claim", ""),
            probability=float(data.get("probability", 0.5)),
            created_at=data.get("created_at", datetime.now().isoformat()),
            resolve_by=data.get("resolve_by"),
            status=PredictionStatus(data.get("status", "open")),
            outcome=data.get("outcome"),
            outcome_note=data.get("outcome_note", ""),
            resolved_at=data.get("resolved_at"),
            brier=data.get("brier"),
            tags=data.get("tags", []),
        )


class AlreadyResolved(Exception):
    """Refusing to rewrite history."""


def brier_score(probability: float, outcome: bool) -> float:
    """
    Squared error between what we said and what happened.

    0 is perfect, 1 is maximally wrong, 0.25 is what you get by always saying
    "50%". It is a proper score: the way to improve it is to be better
    calibrated, not to hedge.
    """
    return (probability - (1.0 if outcome else 0.0)) ** 2


class CalibrationStore:
    """Records predictions and, later, what actually happened."""

    DIR = os.path.join(Config.UPLOAD_FOLDER, 'calibration')

    # ---- storage -------------------------------------------------------

    @classmethod
    def _path(cls, prediction_id: str) -> str:
        validate_storage_id(prediction_id, "prediction_id")
        return safe_join(cls.DIR, f"{prediction_id}.json")

    @classmethod
    def _write(cls, prediction: Prediction) -> None:
        os.makedirs(cls.DIR, exist_ok=True)
        path = cls._path(prediction.prediction_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(prediction.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ---- recording -----------------------------------------------------

    @classmethod
    def record(
        cls,
        question: str,
        claim: str,
        probability: float,
        owner_key_id: Optional[str] = None,
        crowd_id: Optional[str] = None,
        simulation_id: Optional[str] = None,
        resolve_by: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Prediction:
        """
        Write down a claim before reality is known.

        Raises:
            ValueError: the claim is empty or the probability is not a
                probability
        """
        if not question or not question.strip():
            raise ValueError("A prediction needs the question it answers.")
        if not claim or not claim.strip():
            raise ValueError("A prediction needs a falsifiable claim.")
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            raise ValueError("probability must be a number between 0 and 1")
        if not 0.0 <= float(probability) <= 1.0:
            raise ValueError(f"probability must be between 0 and 1, got {probability}")

        prediction = Prediction(
            prediction_id=f"pred_{uuid.uuid4().hex[:12]}",
            crowd_id=crowd_id,
            simulation_id=simulation_id,
            owner_key_id=owner_key_id,
            question=question.strip(),
            claim=claim.strip(),
            probability=float(probability),
            created_at=datetime.now().isoformat(),
            resolve_by=resolve_by,
            tags=tags or [],
        )
        cls._write(prediction)
        logger.info(
            f"Recorded {prediction.prediction_id} at p={probability}: {claim[:60]}"
        )
        return prediction

    @classmethod
    def resolve(
        cls,
        prediction_id: str,
        outcome: bool,
        note: str = "",
    ) -> Prediction:
        """
        Record what actually happened, and score the prediction.

        Raises:
            KeyError: no such prediction
            AlreadyResolved: it has already been scored
        """
        prediction = cls.get(prediction_id)
        if prediction is None:
            raise KeyError(f"No such prediction: {prediction_id}")
        if prediction.status == PredictionStatus.RESOLVED:
            # Rewriting a scored prediction would make the whole record
            # worthless, so this is refused rather than trusted to callers.
            raise AlreadyResolved(
                f"{prediction_id} was already resolved on {prediction.resolved_at}"
            )

        prediction.outcome = bool(outcome)
        prediction.outcome_note = note
        prediction.resolved_at = datetime.now().isoformat()
        prediction.brier = brier_score(prediction.probability, bool(outcome))
        prediction.status = PredictionStatus.RESOLVED
        cls._write(prediction)

        logger.info(
            f"Resolved {prediction_id}: said {prediction.probability}, "
            f"got {outcome}, brier {prediction.brier:.3f}"
        )
        return prediction

    # ---- reading -------------------------------------------------------

    @classmethod
    def get(cls, prediction_id: str) -> Optional[Prediction]:
        path = cls._path(prediction_id)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return Prediction.from_dict(json.load(f))

    @classmethod
    def list_for(
        cls,
        owner_key_id: Optional[str],
        status: Optional[PredictionStatus] = None,
    ) -> List[Prediction]:
        if not os.path.isdir(cls.DIR):
            return []
        out = []
        for entry in os.listdir(cls.DIR):
            if not entry.endswith(".json") or entry.endswith(".tmp"):
                continue
            prediction = cls.get(entry[: -len(".json")])
            if prediction is None:
                continue
            if prediction.owner_key_id not in (None, owner_key_id):
                continue
            if status is not None and prediction.status != status:
                continue
            out.append(prediction)
        return sorted(out, key=lambda p: p.created_at, reverse=True)

    # ---- the number that matters ---------------------------------------

    @classmethod
    def scorecard(cls, owner_key_id: Optional[str] = None) -> Dict[str, Any]:
        """
        How good the predictions have actually been.

        `mean_brier` is the headline. `baseline_brier` is what always saying
        "50%" would score, and is reported alongside because a Brier score
        with nothing to compare it to means nothing — 0.24 sounds respectable
        until you notice that coin-flipping scores 0.25.
        """
        resolved = [
            p for p in cls.list_for(owner_key_id)
            if p.status == PredictionStatus.RESOLVED and p.brier is not None
        ]
        open_count = len(
            [p for p in cls.list_for(owner_key_id)
             if p.status == PredictionStatus.OPEN]
        )

        if not resolved:
            return {
                "resolved": 0,
                "open": open_count,
                "mean_brier": None,
                "baseline_brier": 0.25,
                "beats_coin_flip": None,
                "hit_rate": None,
            }

        mean = sum(p.brier for p in resolved) / len(resolved)
        # A "hit" is calling the right side of even odds.
        hits = sum(
            1 for p in resolved
            if (p.probability >= 0.5) == bool(p.outcome)
        )

        return {
            "resolved": len(resolved),
            "open": open_count,
            "mean_brier": round(mean, 4),
            "baseline_brier": 0.25,
            "beats_coin_flip": mean < 0.25,
            "hit_rate": round(hits / len(resolved), 4),
        }
