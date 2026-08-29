"""
Subscriptions and top-ups.

Two buckets that behave differently: an allowance that refreshes monthly and
does not carry over, and credits bought outright that never expire. Almost
every test here exists to stop one specific way of quietly taking money from a
customer.
"""

import pytest
from datetime import datetime, timedelta

from app.models.access_key import (
    AccessKeyManager, InsufficientCredits, PLANS, SubscriptionStatus,
    TOPUP_PACKS, _add_month, plan_allowance,
)


@pytest.fixture
def keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(AccessKeyManager, "STORE_DIR", str(tmp_path / "billing"))
    return AccessKeyManager


def subscribed(keystore, plan="starter"):
    issued = keystore.issue("Customer", plan=plan, subscribe=True)
    return issued["record"]["public_id"]


# --- pricing shape --------------------------------------------------------

def test_every_plan_has_an_allowance_and_a_price():
    for name, plan in PLANS.items():
        assert plan["monthly_credits"] >= 0, name
        assert plan["price_usd"] >= 0, name
        assert plan["label"], name


def test_topups_cost_more_per_credit_than_every_paid_plan():
    """
    Overflow must be more expensive than committing, or the subscription has
    no reason to exist and everyone stays on pay-as-you-go.
    """
    paid_plans = [p for p in PLANS.values() if p["price_usd"] > 0]
    best_plan_rate = min(p["price_usd"] / p["monthly_credits"] for p in paid_plans)
    worst_topup_rate = min(p["price_usd"] / p["credits"] for p in TOPUP_PACKS.values())
    assert worst_topup_rate > best_plan_rate, (
        "the cheapest top-up undercuts a subscription, which inverts the incentive"
    )


# --- the two buckets ------------------------------------------------------

def test_subscribing_grants_the_allowance(keystore):
    pid = subscribed(keystore, "pro")
    record = keystore.get(pid)
    assert record.subscription_credits == plan_allowance("pro")
    assert record.topup_credits == 0
    assert record.credits_remaining == plan_allowance("pro")
    assert record.subscription_status == SubscriptionStatus.ACTIVE


def test_a_bare_grant_is_permanent_not_an_allowance(keystore):
    """`--credits` on the CLI must not evaporate at the next rollover."""
    issued = keystore.issue("Gift", credits=500)
    record = keystore.get(issued["record"]["public_id"])
    assert record.topup_credits == 500
    assert record.subscription_credits == 0


def test_topups_land_in_the_permanent_bucket(keystore):
    pid = subscribed(keystore, "starter")
    keystore.add_topup(pid, 750)
    record = keystore.get(pid)
    assert record.topup_credits == 750
    assert record.subscription_credits == plan_allowance("starter")
    assert record.credits_remaining == plan_allowance("starter") + 750


def test_a_topup_must_be_positive(keystore):
    pid = subscribed(keystore)
    for bad in (0, -10):
        with pytest.raises(ValueError):
            keystore.add_topup(pid, bad)


# --- spend order: the thing that decides whether customers lose money -----

def test_charges_drain_the_expiring_bucket_first(keystore):
    pid = subscribed(keystore, "starter")           # 1000 allowance
    keystore.add_topup(pid, 500)                    # + 500 permanent

    keystore.charge(pid, 300)
    record = keystore.get(pid)
    assert record.subscription_credits == 700, "should have spent the allowance"
    assert record.topup_credits == 500, "permanent credits must be untouched"


def test_a_charge_spanning_both_buckets_empties_the_allowance_first(keystore):
    pid = subscribed(keystore, "starter")           # 1000
    keystore.add_topup(pid, 500)

    keystore.charge(pid, 1200)
    record = keystore.get(pid)
    assert record.subscription_credits == 0
    assert record.topup_credits == 300
    assert record.credits_remaining == 300


def test_topups_alone_can_pay(keystore):
    issued = keystore.issue("PAYG", credits=100)
    pid = issued["record"]["public_id"]
    keystore.charge(pid, 60)
    assert keystore.get(pid).topup_credits == 40


def test_the_combined_balance_is_what_gets_checked(keystore):
    pid = subscribed(keystore, "trial")             # 100
    keystore.add_topup(pid, 50)
    keystore.charge(pid, 150)                       # exactly both buckets
    assert keystore.get(pid).credits_remaining == 0

    with pytest.raises(InsufficientCredits):
        keystore.charge(pid, 1)


def test_refunds_land_where_they_cannot_expire(keystore):
    """
    A refund into an allowance that expires tonight is a refund in name only.
    """
    pid = subscribed(keystore, "starter")
    keystore.charge(pid, 100)
    keystore.refund(pid, 100)

    record = keystore.get(pid)
    assert record.topup_credits == 100
    assert record.credits_remaining == plan_allowance("starter")


# --- renewal --------------------------------------------------------------

def _expire_period(keystore, pid, days_ago=1):
    """Backdate the period so the next read rolls it."""
    record = keystore.get(pid)
    past = (datetime.now() - timedelta(days=days_ago)).isoformat()
    record.period_start = (datetime.now() - timedelta(days=days_ago + 30)).isoformat()
    record.period_end = past
    with keystore._connect(write=True) as conn:
        keystore._upsert(conn, record)
    return record


def test_the_allowance_refreshes_when_the_period_rolls(keystore):
    pid = subscribed(keystore, "starter")
    keystore.charge(pid, 900)
    assert keystore.get(pid).subscription_credits == 100

    _expire_period(keystore, pid)
    assert keystore.get(pid).subscription_credits == plan_allowance("starter")


def test_an_unused_allowance_does_not_stack(keystore):
    """
    "1,000 a month" means 1,000 this month, not 3,000 after three quiet months.
    """
    pid = subscribed(keystore, "starter")
    _expire_period(keystore, pid, days_ago=70)      # two periods missed
    assert keystore.get(pid).subscription_credits == plan_allowance("starter")


def test_rolling_the_period_never_touches_topups(keystore):
    pid = subscribed(keystore, "starter")
    keystore.add_topup(pid, 400)
    _expire_period(keystore, pid)
    assert keystore.get(pid).topup_credits == 400


def test_a_lapsed_subscription_does_not_refill(keystore):
    """Past due must stop the allowance, or a failed card is free service."""
    pid = subscribed(keystore, "starter")
    keystore.set_subscription_status(pid, SubscriptionStatus.PAST_DUE)
    assert keystore.get(pid).subscription_credits == 0

    _expire_period(keystore, pid)
    assert keystore.get(pid).subscription_credits == 0


def test_a_lapsed_customer_keeps_what_they_bought(keystore):
    pid = subscribed(keystore, "starter")
    keystore.add_topup(pid, 600)
    keystore.set_subscription_status(pid, SubscriptionStatus.PAST_DUE)

    record = keystore.get(pid)
    assert record.topup_credits == 600
    assert record.credits_remaining == 600
    keystore.charge(pid, 600)                       # and can still spend them


def test_renewing_sets_the_allowance_rather_than_adding_to_it(keystore):
    pid = subscribed(keystore, "pro")
    keystore.charge(pid, 1000)
    keystore.renew_subscription(pid)
    assert keystore.get(pid).subscription_credits == plan_allowance("pro")


def test_upgrading_grants_the_new_allowance(keystore):
    pid = subscribed(keystore, "starter")
    keystore.start_subscription(pid, "scale")
    record = keystore.get(pid)
    assert record.plan == "scale"
    assert record.subscription_credits == plan_allowance("scale")


def test_an_unknown_plan_is_refused(keystore):
    pid = subscribed(keystore)
    with pytest.raises(ValueError):
        keystore.start_subscription(pid, "enterprise-platinum")


# --- period arithmetic ----------------------------------------------------

@pytest.mark.parametrize("start,expected_month,expected_day", [
    ("2026-01-15T10:00:00", 2, 15),
    ("2026-01-31T10:00:00", 2, 28),   # short month, not a crash
    ("2026-12-15T10:00:00", 1, 15),   # year rollover
])
def test_period_arithmetic(start, expected_month, expected_day):
    nxt = datetime.fromisoformat(_add_month(start))
    assert nxt.month == expected_month
    assert nxt.day == expected_day


# --- the ledger -----------------------------------------------------------

def test_every_movement_is_recorded(keystore):
    pid = subscribed(keystore, "starter")
    keystore.add_topup(pid, 200)
    keystore.charge(pid, 50, reason="crowd_ask")
    keystore.refund(pid, 50, reason="failed")

    entries = keystore.ledger(pid)
    kinds = [e["bucket"] for e in entries]
    assert "topup" in kinds and "charge" in kinds and "refund" in kinds
    # newest first, and the running balance is recorded alongside
    assert entries[0]["balance_after"] == keystore.get(pid).credits_remaining


def test_the_ledger_reconstructs_the_balance(keystore):
    """A disputed balance has to be explainable from the record."""
    pid = subscribed(keystore, "starter")
    keystore.add_topup(pid, 300)
    keystore.charge(pid, 120)
    keystore.charge(pid, 30)

    total = sum(e["delta"] for e in keystore.ledger(pid))
    assert total == keystore.get(pid).credits_remaining
