"""
Stripe fulfilment.

The webhook is the endpoint that turns HTTP requests into money, so most of
these tests are about the ways it must refuse to do that.
"""

import hashlib
import hmac
import json
import sys
import time

import pytest

from app.models.access_key import (
    AccessKeyManager, SubscriptionStatus, plan_allowance,
)
from app.services import stripe_billing

WEBHOOK_SECRET = "whsec_test_secret_for_signing"


@pytest.fixture
def keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(AccessKeyManager, "STORE_DIR", str(tmp_path / "billing"))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    return AccessKeyManager


@pytest.fixture
def customer(keystore):
    issued = keystore.issue("Stripe Customer", plan="starter", credits=0)
    return issued


def sign(payload: bytes, secret: str = WEBHOOK_SECRET, timestamp: int = None) -> str:
    """Build a real Stripe-Signature header."""
    timestamp = timestamp or int(time.time())
    signed = f"{timestamp}.".encode() + payload
    mac = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def event(kind: str, obj: dict) -> bytes:
    return json.dumps({"type": kind, "data": {"object": obj}}).encode()


# --- signature verification -----------------------------------------------

def test_a_correctly_signed_event_verifies(keystore):
    payload = event("checkout.session.completed", {"id": "cs_1"})
    verified = stripe_billing.verify_event(payload, sign(payload))
    assert verified["type"] == "checkout.session.completed"


def test_an_unsigned_payload_is_rejected(keystore):
    payload = event("checkout.session.completed", {"id": "cs_1"})
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.verify_event(payload, None)


def test_a_wrongly_signed_payload_is_rejected(keystore):
    payload = event("checkout.session.completed", {"id": "cs_1"})
    forged = sign(payload, secret="whsec_the_attackers_own_secret")
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.verify_event(payload, forged)


def test_a_tampered_payload_is_rejected(keystore):
    """Sign a small top-up, then swap in a big one."""
    honest = event("checkout.session.completed",
                   {"metadata": {"kind": "topup", "credits": "500"}})
    header = sign(honest)
    tampered = honest.replace(b'"500"', b'"500000"')
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.verify_event(tampered, header)


def test_a_replayed_old_event_is_rejected(keystore):
    """An old signature stays valid forever without a timestamp tolerance."""
    payload = event("checkout.session.completed", {"id": "cs_1"})
    stale = sign(payload, timestamp=int(time.time()) - 60 * 60 * 24)
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.verify_event(payload, stale)


def test_without_a_configured_secret_nothing_verifies(keystore, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    payload = event("checkout.session.completed", {"id": "cs_1"})
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.verify_event(payload, sign(payload))


def test_a_missing_secret_key_is_rejected_not_crashed(keystore, monkeypatch):
    """A signing secret without an API key is still a refusal, not a 500."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    payload = event("checkout.session.completed", {"id": "cs_1"})
    with pytest.raises(stripe_billing.WebhookRejected) as rejected:
        stripe_billing.verify_event(payload, sign(payload))
    assert not isinstance(rejected.value, stripe_billing.StripeNotConfigured)
    assert isinstance(
        rejected.value.__cause__, stripe_billing.StripeNotConfigured
    )


def test_a_missing_stripe_sdk_is_rejected_not_crashed(keystore, monkeypatch):
    """An uninstalled SDK makes `import stripe` raise; that is still a refusal."""
    monkeypatch.setitem(sys.modules, "stripe", None)
    payload = event("checkout.session.completed", {"id": "cs_1"})
    with pytest.raises(stripe_billing.WebhookRejected) as rejected:
        stripe_billing.verify_event(payload, sign(payload))
    assert isinstance(rejected.value.__cause__, ImportError)


# --- fulfilment -----------------------------------------------------------

def test_a_paid_topup_adds_permanent_credits(keystore, customer):
    pid = customer["record"]["public_id"]
    outcome, who = stripe_billing.handle_event({
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_1", "client_reference_id": pid,
            "metadata": {"kind": "topup", "credits": "2000", "public_id": pid},
        }},
    })
    assert who == pid
    record = keystore.get(pid)
    assert record.topup_credits == 2000
    assert record.subscription_credits == 0


def test_a_paid_subscription_grants_the_allowance(keystore, customer):
    pid = customer["record"]["public_id"]
    stripe_billing.handle_event({
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_2", "client_reference_id": pid,
            "customer": "cus_1", "subscription": "sub_1",
            "metadata": {"kind": "subscription", "plan": "pro", "public_id": pid},
        }},
    })
    record = keystore.get(pid)
    assert record.plan == "pro"
    assert record.subscription_credits == plan_allowance("pro")
    assert record.subscription_status == SubscriptionStatus.ACTIVE
    assert record.stripe_subscription_id == "sub_1"


def test_a_renewal_refreshes_rather_than_stacks(keystore, customer):
    pid = customer["record"]["public_id"]
    keystore.start_subscription(pid, "starter", stripe_subscription_id="sub_2")
    keystore.charge(pid, 900)

    stripe_billing.handle_event({
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "subscription": "sub_2", "billing_reason": "subscription_cycle",
        }},
    })
    assert keystore.get(pid).subscription_credits == plan_allowance("starter")


def test_the_first_invoice_does_not_double_grant(keystore, customer):
    """
    checkout.session.completed already granted it. The create invoice must not
    be treated as a renewal.
    """
    pid = customer["record"]["public_id"]
    keystore.start_subscription(pid, "starter", stripe_subscription_id="sub_3")
    keystore.charge(pid, 400)
    before = keystore.get(pid).subscription_credits

    stripe_billing.handle_event({
        "type": "invoice.payment_succeeded",
        "data": {"object": {
            "subscription": "sub_3", "billing_reason": "subscription_create",
        }},
    })
    assert keystore.get(pid).subscription_credits == before


def test_a_failed_payment_stops_the_allowance_but_not_the_topups(keystore, customer):
    pid = customer["record"]["public_id"]
    keystore.start_subscription(pid, "starter", stripe_subscription_id="sub_4")
    keystore.add_topup(pid, 750)

    stripe_billing.handle_event({
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_4"}},
    })
    record = keystore.get(pid)
    assert record.subscription_status == SubscriptionStatus.PAST_DUE
    assert record.subscription_credits == 0
    assert record.topup_credits == 750


def test_cancellation_is_recorded(keystore, customer):
    pid = customer["record"]["public_id"]
    keystore.start_subscription(pid, "pro", stripe_subscription_id="sub_5")
    stripe_billing.handle_event({
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_5"}},
    })
    assert keystore.get(pid).subscription_status == SubscriptionStatus.CANCELED


def test_a_session_with_no_key_is_refused(keystore):
    """Better to fail loudly than credit a stranger."""
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.handle_event({
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_x", "metadata": {"kind": "topup",
                                                           "credits": "100"}}},
        })


def test_a_topup_with_no_amount_is_refused(keystore, customer):
    pid = customer["record"]["public_id"]
    with pytest.raises(stripe_billing.WebhookRejected):
        stripe_billing.handle_event({
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": pid,
                                "metadata": {"kind": "topup", "public_id": pid}}},
        })


def test_unrecognised_events_are_ignored_not_failed(keystore):
    """
    Stripe sends plenty we never asked for. Erroring makes it retry forever.
    """
    outcome, _ = stripe_billing.handle_event({
        "type": "customer.discount.created", "data": {"object": {}},
    })
    assert outcome.startswith("ignored")


# --- over HTTP ------------------------------------------------------------

def test_the_webhook_endpoint_refuses_an_unsigned_body(app, client, keystore,
                                                       customer):
    """The whole point: no signature, no credits."""
    pid = customer["record"]["public_id"]
    before = keystore.get(pid).credits_remaining

    payload = event("checkout.session.completed", {
        "client_reference_id": pid,
        "metadata": {"kind": "topup", "credits": "999999", "public_id": pid},
    })
    r = client.post("/api/account/stripe/webhook", data=payload,
                    content_type="application/json")

    assert r.status_code == 400
    assert keystore.get(pid).credits_remaining == before, "unsigned request minted credits"


def test_the_webhook_endpoint_fulfils_a_signed_body(app, client, keystore, customer):
    pid = customer["record"]["public_id"]
    payload = event("checkout.session.completed", {
        "id": "cs_ok", "client_reference_id": pid,
        "metadata": {"kind": "topup", "credits": "1500", "public_id": pid},
    })
    r = client.post("/api/account/stripe/webhook", data=payload,
                    content_type="application/json",
                    headers={"Stripe-Signature": sign(payload)})

    assert r.status_code == 200
    assert keystore.get(pid).topup_credits == 1500


def test_the_plans_endpoint_is_public(app, client, keystore):
    r = client.get("/api/account/plans")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert {p["id"] for p in data["plans"]} >= {"starter", "pro", "scale"}
    assert {p["id"] for p in data["topups"]} >= {"small", "medium", "large"}


def test_checkout_needs_a_key(app, client, keystore):
    assert client.post("/api/account/checkout/topup",
                       json={"pack": "small"}).status_code == 401


def test_checkout_rejects_an_unknown_pack(app, client, keystore, customer):
    r = client.post("/api/account/checkout/topup", json={"pack": "enormous"},
                    headers={"Authorization": f"Bearer {customer['key']}"})
    assert r.status_code == 400


def test_checkout_reports_when_payments_are_switched_off(app, client, keystore,
                                                         customer, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    r = client.post("/api/account/checkout/topup", json={"pack": "small"},
                    headers={"Authorization": f"Bearer {customer['key']}"})
    assert r.status_code == 503


def test_the_ledger_is_readable_by_its_owner(app, client, keystore, customer):
    pid = customer["record"]["public_id"]
    keystore.add_topup(pid, 100)
    r = client.get("/api/account/ledger",
                   headers={"Authorization": f"Bearer {customer['key']}"})
    assert r.status_code == 200
    assert any(e["bucket"] == "topup" for e in r.get_json()["data"])
