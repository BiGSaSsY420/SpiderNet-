"""
Calibration: the record of what we said versus what happened.

This is the only asset here that compounds, so the tests care most about the
things that would silently make the record worthless — a rewritten prediction,
a score that flatters, a Brier with nothing to compare it against.
"""

import pytest

from app.models.calibration import (
    AlreadyResolved, CalibrationStore, PredictionStatus, brier_score,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(CalibrationStore, "DIR", str(tmp_path / "calibration"))
    return CalibrationStore


def auth(key):
    return {"Authorization": f"Bearer {key}"}


# --- scoring --------------------------------------------------------------

@pytest.mark.parametrize("probability,outcome,expected", [
    (1.0, True, 0.0),      # certain and right
    (0.0, False, 0.0),     # certain and right the other way
    (1.0, False, 1.0),     # certain and wrong: maximally punished
    (0.0, True, 1.0),
    (0.5, True, 0.25),     # coin flip
    (0.5, False, 0.25),
    (0.8, True, 0.04),
])
def test_brier_score(probability, outcome, expected):
    assert brier_score(probability, outcome) == pytest.approx(expected)


def test_confident_and_wrong_scores_worse_than_hedging():
    """The score has to punish overconfidence, or it teaches the wrong lesson."""
    assert brier_score(0.95, False) > brier_score(0.5, False)


def test_confident_and_right_scores_better_than_hedging():
    assert brier_score(0.95, True) < brier_score(0.5, True)


# --- recording ------------------------------------------------------------

def test_a_prediction_starts_open(store):
    p = store.record(question="Will they complain?", claim="Backlash within a week",
                     probability=0.7)
    assert p.status == PredictionStatus.OPEN
    assert p.outcome is None
    assert p.brier is None


def test_round_trip(store):
    p = store.record(question="Q", claim="C", probability=0.3,
                     owner_key_id="abc", tags=["pricing"])
    assert store.get(p.prediction_id).to_dict() == p.to_dict()


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2, "0.5", None, True, False])
def test_probability_must_be_a_probability(store, bad):
    with pytest.raises(ValueError):
        store.record(question="Q", claim="C", probability=bad)


@pytest.mark.parametrize("field", ["question", "claim"])
def test_empty_claim_or_question_is_refused(store, field):
    kwargs = {"question": "Q", "claim": "C", "probability": 0.5}
    kwargs[field] = "   "
    with pytest.raises(ValueError):
        store.record(**kwargs)


# --- resolving ------------------------------------------------------------

def test_resolving_scores_it(store):
    p = store.record(question="Q", claim="C", probability=0.8)
    resolved = store.resolve(p.prediction_id, outcome=True, note="It happened.")

    assert resolved.status == PredictionStatus.RESOLVED
    assert resolved.outcome is True
    assert resolved.brier == pytest.approx(0.04)
    assert resolved.resolved_at is not None
    assert resolved.outcome_note == "It happened."


def test_a_resolved_prediction_cannot_be_rewritten(store):
    """
    Editing a prediction after seeing the outcome would make the entire record
    worthless. It has to be refused, not merely discouraged.
    """
    p = store.record(question="Q", claim="C", probability=0.9)
    store.resolve(p.prediction_id, outcome=False)

    with pytest.raises(AlreadyResolved):
        store.resolve(p.prediction_id, outcome=True)

    # and the bad score stands
    assert store.get(p.prediction_id).brier == pytest.approx(0.81)


def test_resolving_something_that_does_not_exist(store):
    with pytest.raises(KeyError):
        store.resolve("pred_000000000000", outcome=True)


# --- the scorecard --------------------------------------------------------

def test_scorecard_with_nothing_resolved(store):
    store.record(question="Q", claim="C", probability=0.5)
    card = store.scorecard()
    assert card["resolved"] == 0
    assert card["open"] == 1
    assert card["mean_brier"] is None
    assert card["beats_coin_flip"] is None


def test_scorecard_reports_the_baseline_alongside(store):
    """
    A Brier score alone is meaningless. 0.24 sounds fine until you notice that
    always guessing 50% scores 0.25.
    """
    p = store.record(question="Q", claim="C", probability=0.6)
    store.resolve(p.prediction_id, outcome=True)
    card = store.scorecard()
    assert card["baseline_brier"] == 0.25
    assert card["beats_coin_flip"] is True


def test_a_perfect_forecaster_scores_zero(store):
    for outcome in (True, False, True):
        p = store.record(question="Q", claim="C", probability=1.0 if outcome else 0.0)
        store.resolve(p.prediction_id, outcome=outcome)
    card = store.scorecard()
    assert card["mean_brier"] == 0.0
    assert card["hit_rate"] == 1.0


def test_a_confidently_wrong_forecaster_loses_to_a_coin(store):
    for outcome in (True, False, True):
        p = store.record(question="Q", claim="C", probability=0.0 if outcome else 1.0)
        store.resolve(p.prediction_id, outcome=outcome)
    card = store.scorecard()
    assert card["mean_brier"] == 1.0
    assert card["beats_coin_flip"] is False
    assert card["hit_rate"] == 0.0


def test_open_predictions_do_not_flatter_the_score(store):
    """An unresolved prediction must not count as a win."""
    good = store.record(question="Q", claim="C", probability=1.0)
    store.resolve(good.prediction_id, outcome=True)
    store.record(question="Q", claim="C", probability=0.99)   # left open

    card = store.scorecard()
    assert card["resolved"] == 1
    assert card["open"] == 1
    assert card["mean_brier"] == 0.0


def test_scorecards_are_per_customer(store):
    a = store.record(question="Q", claim="C", probability=1.0, owner_key_id="alice")
    store.resolve(a.prediction_id, outcome=True)
    b = store.record(question="Q", claim="C", probability=1.0, owner_key_id="bob")
    store.resolve(b.prediction_id, outcome=False)

    assert store.scorecard("alice")["mean_brier"] == 0.0
    assert store.scorecard("bob")["mean_brier"] == 1.0


# --- over HTTP ------------------------------------------------------------

@pytest.fixture
def customer(isolated_billing):
    return isolated_billing.issue("Calibration Customer", credits=1000)


def test_recording_a_prediction_is_free(app, client, store, customer,
                                        isolated_billing):
    pid = customer["record"]["public_id"]
    before = isolated_billing.get(pid).credits_remaining

    r = client.post("/api/calibration/predictions",
                    json={"question": "Q?", "claim": "It will happen",
                          "probability": 0.7},
                    headers=auth(customer["key"]))
    assert r.status_code == 201
    assert isolated_billing.get(pid).credits_remaining == before


def test_predictions_need_a_key(app, client, store):
    r = client.post("/api/calibration/predictions",
                    json={"question": "Q", "claim": "C", "probability": 0.5})
    assert r.status_code == 401


def test_a_bad_probability_is_a_400(app, client, store, customer):
    r = client.post("/api/calibration/predictions",
                    json={"question": "Q", "claim": "C", "probability": 42},
                    headers=auth(customer["key"]))
    assert r.status_code == 400


def test_resolving_twice_is_a_409(app, client, store, customer):
    created = client.post("/api/calibration/predictions",
                          json={"question": "Q", "claim": "C", "probability": 0.5},
                          headers=auth(customer["key"])).get_json()["data"]
    pid = created["prediction_id"]

    first = client.post(f"/api/calibration/predictions/{pid}/outcome",
                        json={"outcome": True}, headers=auth(customer["key"]))
    assert first.status_code == 200

    second = client.post(f"/api/calibration/predictions/{pid}/outcome",
                         json={"outcome": False}, headers=auth(customer["key"]))
    assert second.status_code == 409


def test_outcome_must_be_a_boolean(app, client, store, customer):
    created = client.post("/api/calibration/predictions",
                          json={"question": "Q", "claim": "C", "probability": 0.5},
                          headers=auth(customer["key"])).get_json()["data"]
    r = client.post(f"/api/calibration/predictions/{created['prediction_id']}/outcome",
                    json={"outcome": "yes"}, headers=auth(customer["key"]))
    assert r.status_code == 400


def test_you_cannot_resolve_someone_elses_prediction(app, client, store,
                                                     isolated_billing):
    alice = isolated_billing.issue("Alice", credits=100)
    bob = isolated_billing.issue("Bob", credits=100)

    created = client.post("/api/calibration/predictions",
                          json={"question": "Q", "claim": "C", "probability": 0.5},
                          headers=auth(alice["key"])).get_json()["data"]

    r = client.post(f"/api/calibration/predictions/{created['prediction_id']}/outcome",
                    json={"outcome": True}, headers=auth(bob["key"]))
    assert r.status_code == 404
