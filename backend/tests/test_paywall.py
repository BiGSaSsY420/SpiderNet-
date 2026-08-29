"""The paywall, exercised through HTTP the way a customer hits it."""

import pytest

from app.models.access_key import AccessKeyManager
from app.utils.billing import PRICES

PAID_POSTS = [
    "/api/graph/build",
    "/api/simulation/prepare",
    "/api/simulation/generate-profiles",
    "/api/simulation/start",
    "/api/simulation/interview",
    "/api/simulation/interview/batch",
    "/api/report/generate",
    "/api/report/chat",
]

FREE_GETS = [
    "/health",
    "/api/account/pricing",
]


@pytest.fixture
def billing(tmp_path, monkeypatch):
    monkeypatch.setattr(AccessKeyManager, "STORE_DIR", str(tmp_path / "billing"))
    return AccessKeyManager


@pytest.fixture
def customer(billing):
    issued = billing.issue("Test Customer", plan="pro", credits=1000)
    return issued


def auth(key):
    return {"Authorization": f"Bearer {key}"}


# --- the gate -------------------------------------------------------------

@pytest.mark.parametrize("path", PAID_POSTS)
def test_paid_endpoints_refuse_anonymous_callers(app, client, billing, path):
    app.config["DEBUG"] = False
    r = client.post(path, json={})
    assert r.status_code == 401, f"{path} was reachable without a key"
    assert r.get_json()["success"] is False


@pytest.mark.parametrize("path", PAID_POSTS)
def test_paid_endpoints_refuse_a_bogus_key(app, client, billing, path):
    r = client.post(path, json={}, headers=auth("sn_live_" + "a" * 60))
    assert r.status_code == 401, f"{path} accepted a forged key"


@pytest.mark.parametrize("path", FREE_GETS)
def test_free_endpoints_need_no_key(client, billing, path):
    assert client.get(path).status_code == 200


def test_revoked_key_is_refused(app, client, billing, customer):
    billing.revoke(customer["record"]["public_id"])
    r = client.post("/api/report/chat", json={}, headers=auth(customer["key"]))
    assert r.status_code == 401


def test_error_message_does_not_reveal_whether_a_key_exists(app, client, billing, customer):
    """Unknown, malformed and revoked must be indistinguishable."""
    billing.revoke(customer["record"]["public_id"])
    revoked = client.post("/api/report/chat", json={}, headers=auth(customer["key"]))
    unknown = client.post("/api/report/chat", json={}, headers=auth("sn_live_" + "b" * 60))
    assert revoked.get_json()["error"] == unknown.get_json()["error"]


# --- the key travels in the ways we advertise -----------------------------

def test_key_accepted_via_bearer_header(client, billing, customer):
    r = client.get("/api/account/me", headers=auth(customer["key"]))
    assert r.status_code == 200
    assert r.get_json()["data"]["credits_remaining"] == 1000


def test_key_accepted_via_custom_header(client, billing, customer):
    r = client.get("/api/account/me", headers={"X-SpiderNet-Key": customer["key"]})
    assert r.status_code == 200


def test_key_accepted_via_query_param_for_eventsource(client, billing, customer):
    r = client.get(f"/api/account/me?access_key={customer['key']}")
    assert r.status_code == 200


def test_account_me_never_returns_the_hash(client, billing, customer):
    body = client.get("/api/account/me", headers=auth(customer["key"])).get_json()
    assert "key_hash" not in body["data"]


def test_checking_the_balance_is_free(client, billing, customer):
    for _ in range(5):
        client.get("/api/account/me", headers=auth(customer["key"]))
    balance = client.get("/api/account/me", headers=auth(customer["key"]))
    assert balance.get_json()["data"]["credits_remaining"] == 1000


# --- metering -------------------------------------------------------------

def test_running_out_of_credits_returns_402_not_401(app, client, billing):
    """The customer is known and valid - they just need to top up."""
    issued = billing.issue("Broke Customer", credits=1)
    r = client.post("/api/report/chat", json={}, headers=auth(issued["key"]))
    assert r.status_code == 402
    body = r.get_json()
    assert "credits" in body["error"].lower()


def test_a_failed_operation_refunds_the_customer(app, client, billing, customer):
    """
    We charge up front. If the handler blows up, the customer must not pay for
    work that never happened.
    """
    pid = customer["record"]["public_id"]
    before = billing.get(pid).credits_remaining

    # No body -> the handler rejects it before doing any real work
    client.post("/api/report/chat", json={}, headers=auth(customer["key"]))

    after = billing.get(pid).credits_remaining
    assert after <= before
    # whatever was spent, it was not silently lost on a crash
    assert after >= before - PRICES["report_chat"]


def test_pricing_endpoint_matches_the_enforced_prices(client, billing):
    published = client.get("/api/account/pricing").get_json()["data"]["prices"]
    assert published == PRICES


def test_published_run_total_is_the_sum_of_its_stages(client, billing):
    data = client.get("/api/account/pricing").get_json()["data"]
    expected = (
        PRICES["ontology_generate"] + PRICES["graph_build"]
        + PRICES["simulation_prepare"] + PRICES["profile_generate"]
        + PRICES["simulation_start"] + PRICES["report_generate"]
    )
    assert data["estimated_run_total"] == expected


# --- structural guard -----------------------------------------------------

# Endpoints that legitimately cost us nothing and must stay free. Anything
# else that mutates state or calls an LLM has to be gated.
FREE_BY_DESIGN = {
    "/health",
    "/api/account/pricing",
    # status polling: the customer already paid for the work being polled
    "/api/graph/task/<task_id>",
    "/api/simulation/prepare/status",
    "/api/simulation/env-status",
    "/api/report/generate/status",
    "/api/report/tools/search",
    "/api/report/tools/statistics",
}


def test_every_state_changing_endpoint_is_gated_or_explicitly_free(app):
    """
    A new paid endpoint added without @require_access_key is a hole in the
    paywall that no other test would catch. Fail loudly instead.
    """
    ungated = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = rule.methods - {"HEAD", "OPTIONS"}
        if methods <= {"GET"}:
            continue                       # reads are free
        if rule.rule in FREE_BY_DESIGN:
            continue
        view = app.view_functions[rule.endpoint]
        if not hasattr(view, "__spidernet_cost__"):
            ungated.append(f"{sorted(methods)} {rule.rule}")

    assert not ungated, (
        "These endpoints change state or spend money but are not gated. "
        "Add @require_access_key, or add them to FREE_BY_DESIGN with a reason:\n  "
        + "\n  ".join(sorted(ungated))
    )


def test_gated_endpoints_charge_the_published_price(app):
    """The decorator's cost must come from PRICES, not a stray literal."""
    published = set(PRICES.values()) | {0}
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        view = app.view_functions[rule.endpoint]
        cost = getattr(view, "__spidernet_cost__", None)
        if cost is not None:
            assert cost in published, f"{rule.rule} charges {cost}, which is not in PRICES"


# --- tenant isolation -----------------------------------------------------

def test_a_customer_cannot_read_another_customers_project(app, client, billing):
    alice = billing.issue("Alice", credits=1000)
    bob = billing.issue("Bob", credits=1000)

    from app.models.project import ProjectManager
    project = ProjectManager.create_project(
        name="Alice's work", owner_key_id=alice["record"]["public_id"]
    )

    ok = client.get(f"/api/graph/project/{project.project_id}",
                    headers=auth(alice["key"]))
    assert ok.status_code == 200

    denied = client.get(f"/api/graph/project/{project.project_id}",
                        headers=auth(bob["key"]))
    assert denied.status_code == 404, "Bob could read Alice's project"


def test_a_customer_cannot_delete_another_customers_project(app, client, billing):
    alice = billing.issue("Alice", credits=1000)
    bob = billing.issue("Bob", credits=1000)

    from app.models.project import ProjectManager
    project = ProjectManager.create_project(
        name="Alice's work", owner_key_id=alice["record"]["public_id"]
    )

    denied = client.delete(f"/api/graph/project/{project.project_id}",
                           headers=auth(bob["key"]))
    assert denied.status_code == 404, "Bob deleted Alice's project"
    assert ProjectManager.get_project(project.project_id) is not None


def test_project_listing_only_shows_your_own(app, client, billing):
    alice = billing.issue("Alice", credits=1000)
    bob = billing.issue("Bob", credits=1000)

    from app.models.project import ProjectManager
    ProjectManager.create_project(name="Alice A", owner_key_id=alice["record"]["public_id"])
    ProjectManager.create_project(name="Alice B", owner_key_id=alice["record"]["public_id"])
    ProjectManager.create_project(name="Bob A", owner_key_id=bob["record"]["public_id"])

    listed = client.get("/api/graph/project/list", headers=auth(bob["key"])).get_json()
    names = {p["name"] for p in listed["data"]}
    assert names == {"Bob A"}, f"Bob saw {names}"


def test_denied_and_missing_are_indistinguishable(app, client, billing):
    """A 403 would confirm the resource exists. Both must look like 404."""
    alice = billing.issue("Alice", credits=1000)
    bob = billing.issue("Bob", credits=1000)

    from app.models.project import ProjectManager
    project = ProjectManager.create_project(
        name="Alice's work", owner_key_id=alice["record"]["public_id"]
    )

    denied = client.get(f"/api/graph/project/{project.project_id}", headers=auth(bob["key"]))
    missing = client.get("/api/graph/project/proj_doesnotexist", headers=auth(bob["key"]))
    assert denied.status_code == missing.status_code == 404
