"""
Reusable crowds: the cheap half of the product.

Building a world costs 190 credits and forty minutes. Asking a saved one costs
3 and seconds. These tests pin that difference and the isolation around it.
"""

import pytest

from app.models.crowd import Crowd, CrowdManager, CrowdVisibility
from app.utils.billing import PRICES


class FakeLLM:
    """Answers in character without spending anything."""

    def __init__(self, fail_for=None, replies=None):
        self.fail_for = fail_for or set()
        self.replies = replies or {}
        self.calls = []

    def chat(self, messages, **kwargs):
        system = messages[0]["content"]
        question = messages[-1]["content"]
        self.calls.append((system, question))
        for name in self.fail_for:
            if name in system:
                raise RuntimeError(f"model refused for {name}")
        for needle, reply in self.replies.items():
            if needle in system:
                return reply
        return "I have thoughts about that."


def people(n=5):
    return [
        {
            "user_id": i,
            "user_name": f"user_{i}",
            "name": f"Person {i}",
            "bio": f"Bio for person {i}",
            "persona": f"Person {i} cares deeply about local issues.",
            "age": 30 + i,
            "profession": "Teacher" if i % 2 else "Driver",
            "country": "United States",
        }
        for i in range(n)
    ]


@pytest.fixture
def crowds(tmp_path, monkeypatch):
    monkeypatch.setattr(CrowdManager, "CROWDS_DIR", str(tmp_path / "crowds"))
    return CrowdManager


# --- capture --------------------------------------------------------------

def test_capturing_a_crowd_keeps_everyone(crowds):
    crowd = crowds.create(name="Ohio parents", people=people(7), owner_key_id="abc123")
    assert crowd.size == 7
    assert len(crowds.get_people(crowd.crowd_id)) == 7
    assert crowds.get(crowd.crowd_id).name == "Ohio parents"


def test_an_empty_crowd_is_refused(crowds):
    with pytest.raises(ValueError):
        crowds.create(name="Nobody", people=[])


def test_round_trip_preserves_every_field(crowds):
    crowd = crowds.create(
        name="Test", people=people(2), owner_key_id="abc123",
        description="A description", source_simulation_id="sim_1",
        graph_id="g_1", tags=["a", "b"],
    )
    loaded = crowds.get(crowd.crowd_id)
    assert loaded.to_dict() == crowd.to_dict()


def test_unsafe_crowd_id_is_refused(crowds):
    from app.utils.safe_path import UnsafeIdentifierError
    with pytest.raises(UnsafeIdentifierError):
        crowds.get("../../etc")


# --- polling --------------------------------------------------------------

def test_polling_asks_every_person_in_the_sample(crowds):
    crowd = crowds.create(name="C", people=people(10))
    llm = FakeLLM()
    result = crowds.poll(crowd.crowd_id, "What do you think?", sample_size=4,
                         llm_client=llm)

    assert result["asked"] == 4
    assert result["answered"] == 4
    assert result["failed"] == 0
    assert len(llm.calls) == 4
    assert all(r["answer"] for r in result["responses"])


def test_each_person_is_asked_in_their_own_character(crowds):
    crowd = crowds.create(name="C", people=people(3))
    llm = FakeLLM()
    crowds.poll(crowd.crowd_id, "Q?", sample_size=3, llm_client=llm)

    systems = [system for system, _ in llm.calls]
    for i in range(3):
        assert any(f"Person {i}" in s for s in systems), f"Person {i} was never asked"
    # the persona text has to reach the model, or they are all the same person
    assert all("cares deeply about local issues" in s for s in systems)


def test_the_question_reaches_the_model_unchanged(crowds):
    crowd = crowds.create(name="C", people=people(2))
    llm = FakeLLM()
    crowds.poll(crowd.crowd_id, "Would you switch providers?", sample_size=2,
                llm_client=llm)
    assert all(q == "Would you switch providers?" for _, q in llm.calls)


def test_sample_size_is_capped_by_the_crowd(crowds):
    crowd = crowds.create(name="C", people=people(3))
    result = crowds.poll(crowd.crowd_id, "Q?", sample_size=100, llm_client=FakeLLM())
    assert result["asked"] == 3


def test_polling_is_repeatable(crowds):
    """Two polls of the same crowd must ask the same people, or answers
    cannot be compared across questions."""
    crowd = crowds.create(name="C", people=people(20))
    a = crowds.poll(crowd.crowd_id, "Q1?", sample_size=5, llm_client=FakeLLM())
    b = crowds.poll(crowd.crowd_id, "Q2?", sample_size=5, llm_client=FakeLLM())
    assert {r["name"] for r in a["responses"]} == {r["name"] for r in b["responses"]}


def test_one_persons_failure_does_not_lose_the_others(crowds):
    crowd = crowds.create(name="C", people=people(5))
    llm = FakeLLM(fail_for={"Person 2"})
    result = crowds.poll(crowd.crowd_id, "Q?", sample_size=5, llm_client=llm)

    assert result["answered"] == 4
    assert result["failed"] == 1
    assert result["failures"][0]["name"] == "Person 2"


def test_a_silent_crowd_is_reported_not_hidden(crowds):
    """"Nobody answered" must be distinguishable from "everybody agreed"."""
    crowd = crowds.create(name="C", people=people(3))
    llm = FakeLLM(fail_for={"Person"})
    result = crowds.poll(crowd.crowd_id, "Q?", sample_size=3, llm_client=llm)
    assert result["answered"] == 0
    assert result["failed"] == 3


def test_empty_question_is_refused(crowds):
    crowd = crowds.create(name="C", people=people(2))
    for bad in ["", "   ", None]:
        with pytest.raises(ValueError):
            crowds.poll(crowd.crowd_id, bad, llm_client=FakeLLM())


def test_poll_count_is_tracked(crowds):
    crowd = crowds.create(name="C", people=people(2))
    for _ in range(3):
        crowds.poll(crowd.crowd_id, "Q?", sample_size=1, llm_client=FakeLLM())
    assert crowds.get(crowd.crowd_id).poll_count == 3


# --- visibility -----------------------------------------------------------

def test_you_only_see_your_own_crowds(crowds):
    crowds.create(name="Alice's", people=people(2), owner_key_id="alice")
    crowds.create(name="Bob's", people=people(2), owner_key_id="bob")
    assert {c.name for c in crowds.list_for("bob")} == {"Bob's"}


def test_library_crowds_are_visible_to_everyone(crowds):
    shared = crowds.create(name="US suburban parents", people=people(2),
                           owner_key_id="us")
    shared.visibility = CrowdVisibility.LIBRARY
    crowds._save(shared)

    names = {c.name for c in crowds.list_for("some-other-customer")}
    assert "US suburban parents" in names


# --- the economics the whole thing rests on -------------------------------

def test_asking_is_far_cheaper_than_building():
    full_run = (
        PRICES["ontology_generate"] + PRICES["graph_build"]
        + PRICES["simulation_prepare"] + PRICES["profile_generate"]
        + PRICES["simulation_start"] + PRICES["report_generate"]
    )
    assert PRICES["crowd_ask"] * 20 < full_run, (
        "Reusing a crowd has to be dramatically cheaper than rebuilding one, "
        "or there is no reason for the feature to exist."
    )


# --- over HTTP ------------------------------------------------------------

def auth(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def customer(isolated_billing):
    return isolated_billing.issue("Crowd Customer", plan="pro", credits=1000)


def test_asking_needs_a_key(app, client, crowds, customer):
    crowd = crowds.create(name="C", people=people(2),
                          owner_key_id=customer["record"]["public_id"])
    r = client.post(f"/api/crowds/{crowd.crowd_id}/ask", json={"question": "Q?"})
    assert r.status_code == 401


def test_browsing_crowds_is_free(app, client, crowds, customer, isolated_billing):
    pid = customer["record"]["public_id"]
    before = isolated_billing.get(pid).credits_remaining
    for _ in range(3):
        assert client.get("/api/crowds", headers=auth(customer["key"])).status_code == 200
    assert isolated_billing.get(pid).credits_remaining == before


def test_a_customer_cannot_ask_another_customers_crowd(app, client, crowds,
                                                       isolated_billing):
    alice = isolated_billing.issue("Alice", credits=1000)
    bob = isolated_billing.issue("Bob", credits=1000)
    crowd = crowds.create(name="Alice's", people=people(2),
                          owner_key_id=alice["record"]["public_id"])

    r = client.post(f"/api/crowds/{crowd.crowd_id}/ask",
                    json={"question": "Q?"}, headers=auth(bob["key"]))
    assert r.status_code == 404, "Bob reached Alice's crowd"


def test_a_customer_cannot_delete_another_customers_crowd(app, client, crowds,
                                                          isolated_billing):
    alice = isolated_billing.issue("Alice", credits=1000)
    bob = isolated_billing.issue("Bob", credits=1000)
    crowd = crowds.create(name="Alice's", people=people(2),
                          owner_key_id=alice["record"]["public_id"])

    r = client.delete(f"/api/crowds/{crowd.crowd_id}", headers=auth(bob["key"]))
    assert r.status_code == 404
    assert crowds.get(crowd.crowd_id) is not None


def test_an_empty_question_costs_nothing(app, client, crowds, customer,
                                         isolated_billing):
    pid = customer["record"]["public_id"]
    crowd = crowds.create(name="C", people=people(2), owner_key_id=pid)
    before = isolated_billing.get(pid).credits_remaining

    r = client.post(f"/api/crowds/{crowd.crowd_id}/ask",
                    json={"question": "  "}, headers=auth(customer["key"]))
    assert r.status_code == 400
    # charged up front, refunded on the way out
    assert isolated_billing.get(pid).credits_remaining == before


def test_capturing_a_crowd_from_an_unknown_run_is_a_404(app, client, crowds, customer):
    r = client.post("/api/crowds/from-simulation",
                    json={"simulation_id": "sim_nope0000001", "name": "X"},
                    headers=auth(customer["key"]))
    assert r.status_code == 404


def test_capture_requires_a_name(app, client, crowds, customer):
    r = client.post("/api/crowds/from-simulation",
                    json={"simulation_id": "sim_whatever01"},
                    headers=auth(customer["key"]))
    assert r.status_code == 400


def test_you_cannot_capture_a_crowd_from_another_customers_run(app, client, crowds,
                                                               isolated_billing,
                                                               isolated_storage):
    """The people in a run are the customer's data, not a shared resource."""
    from app.services.simulation_manager import SimulationManager

    alice = isolated_billing.issue("Alice", credits=1000)
    bob = isolated_billing.issue("Bob", credits=1000)

    manager = SimulationManager()
    state = manager.create_simulation(
        project_id="proj_alice0001", graph_id="g_1",
        owner_key_id=alice["record"]["public_id"],
    )

    r = client.post("/api/crowds/from-simulation",
                    json={"simulation_id": state.simulation_id, "name": "Stolen"},
                    headers=auth(bob["key"]))
    assert r.status_code == 404, "Bob captured Alice's people"
