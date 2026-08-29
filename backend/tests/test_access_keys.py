"""Access keys, credit metering and the paywall."""

import os
import pathlib
import threading
import pytest


def pathlib_root() -> str:
    """The backend package root, so a subprocess can import the app."""
    return str(pathlib.Path(__file__).resolve().parent.parent)

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
    """A stolen database must not hand over working keys."""
    issued = keystore.issue("Acme", credits=10)
    raw = (tmp_path / "billing" / "billing.db").read_bytes()
    assert issued["key"].encode() not in raw
    # the hash is there, so we are reading the right file
    assert keystore.get(issued["record"]["public_id"]).key_hash.encode() in raw


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
    "sn_live_" + "z" * 60,          # right length, not hex
    "xx_live_" + "a" * 60,          # wrong prefix
    "sn_live_" + "a" * 59,          # wrong length
    "sn-live-" + "a" * 60,          # wrong separator
])
def test_malformed_keys_are_rejected(keystore, bad):
    assert keystore.verify(bad) is None


def test_unknown_but_wellformed_key_is_rejected(keystore):
    """Correct shape, no such record - must fail as unknown, not as malformed."""
    from app.models.access_key import parse_key
    candidate = "sn_live_" + "a" * 60
    assert parse_key(candidate) is not None, "test fixture is not actually well-formed"
    keystore.issue("real", credits=10)
    assert keystore.verify(candidate) is None


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
    mode = os.stat(tmp_path / "billing" / "billing.db").st_mode & 0o077
    assert mode == 0, "access key store should not be readable by others"


def test_keys_issued_before_sqlite_are_migrated(keystore, tmp_path):
    """Upgrading must not strand a paying customer."""
    import json
    from app.models.access_key import _hash_key

    billing = tmp_path / "billing"
    billing.mkdir(parents=True, exist_ok=True)
    plaintext = "sn_live_" + "ab" * 30
    public_id = plaintext.split("_")[2][:12]

    # The literal shape written before the buckets existed: one balance, no
    # subscription fields.
    legacy = {
        "public_id": public_id,
        "key_hash": _hash_key(plaintext),
        "label": "Legacy Customer",
        "plan": "pro",
        "credits_remaining": 250,
        "credits_used": 10,
        "status": "active",
        "created_at": "2026-01-01T00:00:00",
        "environment": "live",
    }
    (billing / "access_keys.json").write_text(
        json.dumps({public_id: legacy}), encoding="utf-8"
    )

    record = keystore.verify(plaintext)
    assert record is not None, "a key issued before the migration stopped working"
    assert record.credits_remaining == 250
    assert record.label == "Legacy Customer"
    # An old balance is permanent, not an allowance: it must not evaporate at
    # the next rollover just because we changed the schema.
    assert record.topup_credits == 250
    assert record.subscription_credits == 0
    # and the old file is set aside so it cannot be migrated twice
    assert not (billing / "access_keys.json").exists()


def test_concurrent_charges_across_processes_never_oversell(keystore, tmp_path):
    """
    The reason balances live in SQLite rather than a JSON file.

    The threaded test above passes with an in-process lock. This one does not:
    it spends from four separate interpreters, which is what a multi-worker
    deployment actually looks like.
    """
    import subprocess
    import sys
    import os as _os

    issued = keystore.issue("Acme", credits=100)
    pid = issued["record"]["public_id"]
    store_dir = keystore.STORE_DIR

    spender = f'''
import sys
sys.path.insert(0, {str(pathlib_root())!r})
from app.models.access_key import AccessKeyManager, InsufficientCredits
AccessKeyManager.STORE_DIR = {store_dir!r}
won = 0
for _ in range(50):
    try:
        AccessKeyManager.charge({pid!r}, 1)
        won += 1
    except InsufficientCredits:
        pass
# the app logs to stdout, so mark the answer
print("SPENT=%d" % won)
'''
    env = dict(_os.environ, LLM_API_KEY="test", ZEP_API_KEY="test")
    procs = [
        subprocess.Popen([sys.executable, "-c", spender],
                         stdout=subprocess.PIPE, env=env, text=True)
        for _ in range(4)
    ]
    def spent_by(proc):
        out = proc.communicate()[0]
        for line in out.splitlines():
            if line.startswith("SPENT="):
                return int(line.split("=", 1)[1])
        raise AssertionError(f"spender produced no result:\n{out[-400:]}")

    spent = sum(spent_by(p) for p in procs)

    assert spent == 100, f"four processes sold {spent} of 100 credits"
    assert keystore.get(pid).credits_remaining == 0
