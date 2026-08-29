"""Access keys, credit metering and the paywall."""

import os
import threading
import pytest

from app.models.access_key import (
    AccessKeyManager, InsufficientCredits, KeyStatus, parse_key,
)


@pytest.fixture
def keystore(tmp_path, monkeypatch):
    monkeypatch.setattr(AccessKeyManager, "STORE_DIR", str(tmp_path / "billing"))
    return AccessKeyManager


# --- issuing --------------------------------------------------------------

def test_issued_key_verifies(keystore):
    issued = keystore.issue("Acme Corp", plan="pro", credits=100)
    record = keystore.verify(issued["key"])
    assert record is not None
    assert record.label == "Acme Corp"
    assert record.credits_remaining == 100


def test_plaintext_is_never_stored(keystore, tmp_path):
    issued = keystore.issue("Acme", credits=10)
    stored = (tmp_path / "billing" / "access_keys.json").read_text()
    assert issued["key"] not in stored
    assert "key_hash" in stored


def test_issue_response_does_not_echo_the_hash(keystore):
    issued = keystore.issue("Acme", credits=10)
    assert "key_hash" not in issued["record"]


def test_keys_are_unique(keystore):
    keys = {keystore.issue(f"k{i}", credits=1)["key"] for i in range(25)}
    assert len(keys) == 25


def test_negative_credits_rejected(keystore):
    with pytest.raises(ValueError):
        keystore.issue("bad", credits=-5)


# --- verification ---------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "", "   ", None, "garbage", "sn_live_short",
    "sn_live_" + "z" * 72,          # right length, not hex
    "xx_live_" + "a" * 72,          # wrong prefix
    "sn_live_" + "a" * 71,          # wrong length
    "sn-live-" + "a" * 72,          # wrong separator
])
def test_malformed_keys_are_rejected(keystore, bad):
    assert keystore.verify(bad) is None


def test_unknown_but_wellformed_key_is_rejected(keystore):
    keystore.issue("real", credits=10)
    assert keystore.verify("sn_live_" + "a" * 72) is None


def test_right_public_id_wrong_secret_is_rejected(keystore):
    """The public id is not a credential on its own."""
    issued = keystore.issue("real", credits=10)
    public_id = issued["record"]["public_id"]
    forged = f"sn_live_{public_id}{'0' * 48}"
    assert parse_key(forged) == public_id      # shape is right
    assert keystore.verify(forged) is None     # but it still fails


def test_revoked_key_stops_verifying(keystore):
    issued = keystore.issue("temp", credits=10)
    keystore.revoke(issued["record"]["public_id"])
    assert keystore.verify(issued["key"]) is None


def test_zero_balance_still_verifies(keystore):
    """Out of credits is not the same as invalid - the customer can top up."""
    issued = keystore.issue("empty", credits=0)
    record = keystore.verify(issued["key"])
    assert record is not None
    assert record.credits_remaining == 0


# --- metering -------------------------------------------------------------

def test_charge_deducts_and_records(keystore):
    issued = keystore.issue("acme", credits=100)
    pid = issued["record"]["public_id"]
    after = keystore.charge(pid, 40, reason="graph_build")
    assert after.credits_remaining == 60
    assert after.credits_used == 40
    assert after.last_used_at is not None


def test_charge_beyond_balance_is_refused_and_changes_nothing(keystore):
    issued = keystore.issue("acme", credits=30)
    pid = issued["record"]["public_id"]
    with pytest.raises(InsufficientCredits):
        keystore.charge(pid, 40)
    assert keystore.get(pid).credits_remaining == 30


def test_charge_of_exact_balance_succeeds(keystore):
    issued = keystore.issue("acme", credits=40)
    pid = issued["record"]["public_id"]
    assert keystore.charge(pid, 40).credits_remaining == 0


def test_refund_restores_balance(keystore):
    issued = keystore.issue("acme", credits=100)
    pid = issued["record"]["public_id"]
    keystore.charge(pid, 40)
    after = keystore.refund(pid, 40)
    assert after.credits_remaining == 100
    assert after.credits_used == 0


def test_revoked_key_cannot_be_charged(keystore):
    issued = keystore.issue("acme", credits=100)
    pid = issued["record"]["public_id"]
    keystore.revoke(pid)
    with pytest.raises(KeyError):
        keystore.charge(pid, 1)


def test_unknown_key_cannot_be_charged(keystore):
    with pytest.raises(KeyError):
        keystore.charge("deadbeefcafe", 1)


def test_top_up_adds_credits(keystore):
    issued = keystore.issue("acme", credits=10)
    pid = issued["record"]["public_id"]
    assert keystore.top_up(pid, 500).credits_remaining == 510


def test_concurrent_charges_never_oversell(keystore):
    """
    The balance is the product. Two threads must not both spend the last credit.
    """
    issued = keystore.issue("acme", credits=100)
    pid = issued["record"]["public_id"]

    succeeded = []
    refused = []

    def spend():
        try:
            keystore.charge(pid, 1)
            succeeded.append(1)
        except InsufficientCredits:
            refused.append(1)

    threads = [threading.Thread(target=spend) for _ in range(150)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(succeeded) == 100, f"sold {len(succeeded)} of 100 credits"
    assert len(refused) == 50
    assert keystore.get(pid).credits_remaining == 0


# --- administration -------------------------------------------------------

def test_listing_never_exposes_hashes(keystore):
    keystore.issue("a", credits=1)
    keystore.issue("b", credits=1)
    listed = keystore.list_keys()
    assert len(listed) == 2
    for row in listed:
        assert "key_hash" not in row


def test_store_file_is_not_world_readable(keystore, tmp_path):
    keystore.issue("acme", credits=1)
    mode = os.stat(tmp_path / "billing" / "access_keys.json").st_mode & 0o077
    assert mode == 0, "access key store should not be readable by others"
