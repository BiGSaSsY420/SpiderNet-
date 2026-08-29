"""
The operator console.

It sees every customer, every balance and every dollar, so most of these tests
are about who must not be able to reach it.
"""

import pytest

from app.models.access_key import AccessKeyManager, KeyStatus, PLANS
from app.utils import admin_auth

ADMIN_TOKEN = "test-admin-token-long-enough-to-be-accepted-xyz"

ADMIN_GETS = [
    "/api/admin/overview",
    "/api/admin/customers",
    "/api/admin/crowds",
    "/api/admin/status",
]


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("SPIDERNET_ADMIN_TOKEN", ADMIN_TOKEN)
    return {"X-SpiderNet-Admin": ADMIN_TOKEN}


@pytest.fixture
def customer(isolated_billing):
    return isolated_billing.issue("Acme Corp", plan="pro", credits=500)


# --- who cannot get in ----------------------------------------------------

@pytest.mark.parametrize("path", ADMIN_GETS)
def test_anonymous_callers_are_refused(app, client, admin, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_a_wrong_token_is_refused(app, client, admin, path):
    r = client.get(path, headers={"X-SpiderNet-Admin": "not-the-token-but-long-enough-xx"})
    assert r.status_code == 404


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_a_customer_key_cannot_reach_the_console(app, client, admin, customer, path):
    """
    The single worst failure available here: a paying customer reading every
    other customer's balance.
    """
    r = client.get(path, headers={"Authorization": f"Bearer {customer['key']}"})
    assert r.status_code == 404, f"{path} accepted a customer key"


def test_refusal_looks_like_the_endpoint_does_not_exist(app, client, admin):
    """A 401 would confirm there is an admin console here to attack."""
    r = client.get("/api/admin/overview")
    assert r.status_code == 404
    assert "admin" not in (r.get_json() or {}).get("error", "").lower()


# --- fail closed ----------------------------------------------------------

@pytest.mark.parametrize("path", ADMIN_GETS)
def test_with_no_token_configured_the_console_is_off(app, client, monkeypatch, path):
    """A missing environment variable must not open the door."""
    monkeypatch.delenv("SPIDERNET_ADMIN_TOKEN", raising=False)
    assert client.get(path).status_code == 404
    assert client.get(path, headers={"X-SpiderNet-Admin": ""}).status_code == 404


def test_a_short_token_is_treated_as_unconfigured(app, client, monkeypatch):
    """'admin' is not a secret, and must not be accepted as one."""
    monkeypatch.setenv("SPIDERNET_ADMIN_TOKEN", "admin")
    r = client.get("/api/admin/overview", headers={"X-SpiderNet-Admin": "admin"})
    assert r.status_code == 404
    assert not admin_auth.is_enabled()


def test_a_long_enough_token_enables_it(monkeypatch):
    monkeypatch.setenv("SPIDERNET_ADMIN_TOKEN", ADMIN_TOKEN)
    assert admin_auth.is_enabled()


# --- what it shows --------------------------------------------------------

def test_overview_reports_revenue_and_liability(app, client, admin, isolated_billing):
    isolated_billing.issue("Sub One", plan="pro", subscribe=True)
    isolated_billing.issue("Sub Two", plan="starter", subscribe=True)
    isolated_billing.issue("PAYG", credits=300)

    data = client.get("/api/admin/overview", headers=admin).get_json()["data"]

    assert data["customers"] == 3
    assert data["subscribers"] == 2
    assert data["mrr_usd"] == PLANS["pro"]["price_usd"] + PLANS["starter"]["price_usd"]
    assert data["arr_usd"] == data["mrr_usd"] * 12
    # Unspent credits are owed work, not income.
    assert data["credits_outstanding"] == (
        PLANS["pro"]["monthly_credits"] + PLANS["starter"]["monthly_credits"] + 300
    )


def test_spent_credits_move_from_liability_to_delivered(app, client, admin,
                                                        isolated_billing):
    issued = isolated_billing.issue("Spender", credits=1000)
    pid = issued["record"]["public_id"]
    isolated_billing.charge(pid, 250, reason="crowd_ask")

    data = client.get("/api/admin/overview", headers=admin).get_json()["data"]
    assert data["credits_outstanding"] == 750
    assert data["credits_delivered"] == 250
    assert data["credits_spent_30d"] == 250


def test_a_revoked_customer_leaves_the_liability(app, client, admin,
                                                 isolated_billing):
    issued = isolated_billing.issue("Gone", credits=900)
    isolated_billing.revoke(issued["record"]["public_id"])
    data = client.get("/api/admin/overview", headers=admin).get_json()["data"]
    assert data["credits_outstanding"] == 0
    assert data["active_customers"] == 0


def test_the_console_never_returns_key_hashes(app, client, admin, customer):
    """It exists to run the business, not to impersonate people in it."""
    listing = client.get("/api/admin/customers", headers=admin).get_json()
    detail = client.get(
        f"/api/admin/customers/{customer['record']['public_id']}", headers=admin
    ).get_json()

    assert "key_hash" not in str(listing)
    assert "key_hash" not in str(detail)


def test_customer_detail_includes_their_history(app, client, admin, customer,
                                                isolated_billing):
    pid = customer["record"]["public_id"]
    isolated_billing.charge(pid, 100, reason="graph_build")

    data = client.get(f"/api/admin/customers/{pid}", headers=admin).get_json()["data"]
    assert data["public_id"] == pid
    assert any(e["bucket"] == "charge" for e in data["ledger"])
    assert "scorecard" in data


def test_unknown_customer_is_a_404(app, client, admin):
    assert client.get("/api/admin/customers/nope000000",
                      headers=admin).status_code == 404


# --- what it can do -------------------------------------------------------

def test_issuing_a_key_returns_the_plaintext_once(app, client, admin):
    r = client.post("/api/admin/customers",
                    json={"label": "Invoiced Corp", "plan": "pro", "subscribe": True},
                    headers=admin)
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["key"].startswith("sn_live_")
    assert data["record"]["subscription_credits"] == PLANS["pro"]["monthly_credits"]


def test_issuing_needs_a_label(app, client, admin):
    assert client.post("/api/admin/customers", json={}, headers=admin).status_code == 400


def test_granting_credits_adds_to_the_permanent_bucket(app, client, admin, customer,
                                                       isolated_billing):
    pid = customer["record"]["public_id"]
    before = isolated_billing.get(pid).topup_credits

    r = client.post(f"/api/admin/customers/{pid}/credits",
                    json={"credits": 400, "reason": "goodwill"}, headers=admin)
    assert r.status_code == 200
    assert isolated_billing.get(pid).topup_credits == before + 400


@pytest.mark.parametrize("bad", [0, -50, "lots", None])
def test_a_bad_grant_is_refused(app, client, admin, customer, bad):
    pid = customer["record"]["public_id"]
    r = client.post(f"/api/admin/customers/{pid}/credits",
                    json={"credits": bad}, headers=admin)
    assert r.status_code == 400


def test_granting_credits_needs_the_admin_token(app, client, admin, customer,
                                                isolated_billing):
    """A customer must not be able to grant themselves credits."""
    pid = customer["record"]["public_id"]
    before = isolated_billing.get(pid).credits_remaining

    r = client.post(f"/api/admin/customers/{pid}/credits",
                    json={"credits": 100000},
                    headers={"Authorization": f"Bearer {customer['key']}"})
    assert r.status_code == 404
    assert isolated_billing.get(pid).credits_remaining == before


def test_moving_a_customer_onto_a_plan(app, client, admin, customer,
                                       isolated_billing):
    pid = customer["record"]["public_id"]
    r = client.post(f"/api/admin/customers/{pid}/plan",
                    json={"plan": "scale"}, headers=admin)
    assert r.status_code == 200
    assert isolated_billing.get(pid).plan == "scale"


def test_revoking_a_customer(app, client, admin, customer, isolated_billing):
    pid = customer["record"]["public_id"]
    r = client.post(f"/api/admin/customers/{pid}/revoke", headers=admin)
    assert r.status_code == 200
    assert isolated_billing.get(pid).status == KeyStatus.REVOKED
    assert isolated_billing.verify(customer["key"]) is None
