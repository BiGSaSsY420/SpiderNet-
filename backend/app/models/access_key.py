"""
Access keys and credit metering.

SpiderNet is sold as hosted access: the operator holds the LLM and graph-store
credentials, and customers buy a key that draws down a credit balance. A
customer never supplies an API key of their own.

Security notes:
- Only a SHA-256 hash of each key is stored. The plaintext is returned exactly
  once, at creation, and cannot be recovered afterwards.
- Lookup is by a short public id carried in the key itself, so verification is
  a single dict access followed by one constant-time hash comparison.
- Balances are mutated inside a database transaction, not under a process
  lock, so concurrency is safe across workers as well as threads.

Balances live in SQLite rather than a JSON file. That is not premature: the
balance is the product, and a JSON file guarded by an in-process lock is
correct only while exactly one worker process exists. Two gunicorn workers, or
one server plus a cron job, and both can read 1 credit, both can decide it is
enough, and both can spend it.

Every mutation runs in a BEGIN IMMEDIATE transaction, which takes SQLite's
write lock before reading. That serialises charges across processes, not just
across threads. SQLite is the right size for this until there are enough
customers to need a server database, and the swap is contained in this file.
"""

import calendar
import hashlib
import hmac
import json
import os
import sqlite3
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('spidernet.access_key')

KEY_PREFIX = "sn"
PUBLIC_ID_BYTES = 6      # 12 hex chars, identifies the record
SECRET_BYTES = 24        # 48 hex chars of actual entropy


class KeyStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class SubscriptionStatus(str, Enum):
    NONE = "none"          # pay-as-you-go: top-ups only
    ACTIVE = "active"
    PAST_DUE = "past_due"  # payment failed; allowance stops refreshing
    CANCELED = "canceled"  # runs to period end, then stops refreshing


# Monthly allowance per plan, and what it costs.
#
# Top-ups are deliberately priced above every subscription tier per credit
# (see TOPUP_PACKS). Overflow should be more expensive than committing, or the
# subscription has no reason to exist.
PLANS: Dict[str, Dict[str, Any]] = {
    "trial":   {"monthly_credits": 100,    "price_usd": 0,   "label": "Trial"},
    "starter": {"monthly_credits": 1_000,  "price_usd": 49,  "label": "Starter"},
    "pro":     {"monthly_credits": 5_000,  "price_usd": 199, "label": "Pro"},
    "scale":   {"monthly_credits": 25_000, "price_usd": 849, "label": "Scale"},
}

# One-off credit packs. These never expire, which is why they cost more.
TOPUP_PACKS: Dict[str, Dict[str, Any]] = {
    "small":  {"credits": 500,    "price_usd": 34,  "label": "500 credits"},
    "medium": {"credits": 2_000,  "price_usd": 119, "label": "2,000 credits"},
    "large":  {"credits": 10_000, "price_usd": 499, "label": "10,000 credits"},
}


def plan_allowance(plan: str) -> int:
    return PLANS.get(plan, {}).get("monthly_credits", 0)


def _add_month(iso: str) -> str:
    """One billing period on from an ISO timestamp, clamped for short months."""
    when = datetime.fromisoformat(iso)
    year, month = when.year, when.month + 1
    if month > 12:
        year, month = year + 1, 1
    # 31 Jan + 1 month is 28/29 Feb, not an error
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day).isoformat()


@dataclass
class AccessKey:
    """A sold key. Never holds the plaintext."""
    public_id: str
    key_hash: str
    label: str
    plan: str

    # Two buckets, because they behave differently.
    #
    # subscription_credits refresh every billing period and do not carry over.
    # topup_credits were bought outright and never expire. Charges drain the
    # subscription bucket first: spending the permanent one while the monthly
    # one silently expired would take money from the customer for nothing.
    subscription_credits: int = 0
    topup_credits: int = 0

    credits_used: int = 0
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used_at: Optional[str] = None
    environment: str = "live"

    subscription_status: SubscriptionStatus = SubscriptionStatus.NONE
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None

    @property
    def credits_remaining(self) -> int:
        """What the customer can actually spend right now."""
        return self.subscription_credits + self.topup_credits

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, KeyStatus) else self.status
        d["subscription_status"] = (
            self.subscription_status.value
            if isinstance(self.subscription_status, SubscriptionStatus)
            else self.subscription_status
        )
        return d

    def to_public_dict(self) -> Dict[str, Any]:
        """What is safe to show a customer about their own key."""
        return {
            "public_id": self.public_id,
            "label": self.label,
            "plan": self.plan,
            "plan_label": PLANS.get(self.plan, {}).get("label", self.plan),
            "credits_remaining": self.credits_remaining,
            "subscription_credits": self.subscription_credits,
            "topup_credits": self.topup_credits,
            "monthly_allowance": plan_allowance(self.plan),
            "credits_used": self.credits_used,
            "status": self.status.value if isinstance(self.status, KeyStatus) else self.status,
            "subscription_status": (
                self.subscription_status.value
                if isinstance(self.subscription_status, SubscriptionStatus)
                else self.subscription_status
            ),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AccessKey':
        status = data.get("status", "active")
        return cls(
            public_id=data["public_id"],
            key_hash=data["key_hash"],
            label=data.get("label", ""),
            plan=data.get("plan", "starter"),
            # Rows written before the split carried one credits_remaining
            # column. Treat that as bought-outright, so nobody's balance
            # evaporates at the next period rollover.
            subscription_credits=int(
                data.get("subscription_credits", 0)
            ),
            topup_credits=int(
                data.get("topup_credits", data.get("credits_remaining", 0) or 0)
            ),
            credits_used=int(data.get("credits_used", 0)),
            status=KeyStatus(status),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_used_at=data.get("last_used_at"),
            environment=data.get("environment", "live"),
            subscription_status=SubscriptionStatus(
                data.get("subscription_status", "none") or "none"
            ),
            period_start=data.get("period_start"),
            period_end=data.get("period_end"),
            stripe_customer_id=data.get("stripe_customer_id"),
            stripe_subscription_id=data.get("stripe_subscription_id"),
        )


class InsufficientCredits(Exception):
    """Raised when a key cannot cover an operation."""

    def __init__(self, required: int, remaining: int):
        self.required = required
        self.remaining = remaining
        super().__init__(
            f"This operation needs {required} credits, but only {remaining} remain."
        )


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def parse_key(plaintext: str) -> Optional[str]:
    """
    Pull the public id out of a presented key without trusting it.

    Format: sn_<env>_<public_id><secret>
    Returns the public id, or None if the shape is wrong.
    """
    if not isinstance(plaintext, str):
        return None
    parts = plaintext.strip().split("_")
    if len(parts) != 3:
        return None
    prefix, env, body = parts
    if prefix != KEY_PREFIX or not env.isalnum():
        return None
    if len(body) != (PUBLIC_ID_BYTES + SECRET_BYTES) * 2:
        return None
    try:
        int(body, 16)
    except ValueError:
        return None
    return body[: PUBLIC_ID_BYTES * 2]


class AccessKeyManager:
    """Issues, verifies and meters access keys."""

    STORE_DIR = os.path.join(Config.UPLOAD_FOLDER, 'billing')
    # Only read now, to migrate keys issued before the SQLite store existed.
    STORE_FILE = 'access_keys.json'

    # ---- storage -------------------------------------------------------

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS access_keys (
        public_id         TEXT PRIMARY KEY,
        key_hash          TEXT NOT NULL,
        label             TEXT NOT NULL DEFAULT '',
        plan              TEXT NOT NULL DEFAULT 'starter',
        subscription_credits INTEGER NOT NULL DEFAULT 0,
        topup_credits        INTEGER NOT NULL DEFAULT 0,
        credits_used      INTEGER NOT NULL DEFAULT 0,
        status            TEXT NOT NULL DEFAULT 'active',
        created_at        TEXT NOT NULL,
        last_used_at      TEXT,
        environment       TEXT NOT NULL DEFAULT 'live',
        subscription_status   TEXT NOT NULL DEFAULT 'none',
        period_start          TEXT,
        period_end            TEXT,
        stripe_customer_id    TEXT,
        stripe_subscription_id TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_access_keys_hash ON access_keys(key_hash);
    CREATE INDEX IF NOT EXISTS idx_access_keys_sub
        ON access_keys(stripe_subscription_id);

    -- Every credit movement, so a disputed balance can be reconstructed.
    CREATE TABLE IF NOT EXISTS credit_ledger (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        public_id   TEXT NOT NULL,
        delta       INTEGER NOT NULL,
        bucket      TEXT NOT NULL,
        reason      TEXT NOT NULL DEFAULT '',
        balance_after INTEGER NOT NULL,
        at          TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ledger_key ON credit_ledger(public_id, id);
    """

    @classmethod
    def _db_path(cls) -> str:
        return os.path.join(cls.STORE_DIR, 'billing.db')

    @classmethod
    @contextmanager
    def _connect(cls, write: bool = False):
        """
        A connection with the right locking for what it is about to do.

        `write=True` opens with BEGIN IMMEDIATE, which acquires SQLite's write
        lock before any read. Without it, two processes can both read a balance
        of 1, both decide it covers the charge, and both spend it.
        """
        os.makedirs(cls.STORE_DIR, exist_ok=True)
        path = cls._db_path()
        fresh = not os.path.exists(path)

        conn = sqlite3.connect(path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(cls.SCHEMA)
            if fresh:
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
                cls._migrate_from_json(conn)

            if write:
                conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                if write:
                    conn.execute("COMMIT")
            except Exception:
                if write:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    @classmethod
    def _migrate_from_json(cls, conn) -> None:
        """Carry over keys issued before the SQLite store existed."""
        legacy = os.path.join(cls.STORE_DIR, cls.STORE_FILE)
        if not os.path.exists(legacy):
            return
        try:
            with open(legacy, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Could not read the legacy key store at {legacy}: {e}")
            return

        for record in raw.values():
            key = AccessKey.from_dict(record)
            cls._upsert(conn, key)
        logger.info(f"Migrated {len(raw)} access keys from {legacy} into SQLite")
        os.replace(legacy, f"{legacy}.migrated")

    @staticmethod
    def _upsert(conn, key: 'AccessKey') -> None:
        conn.execute(
            """
            INSERT INTO access_keys (
                public_id, key_hash, label, plan,
                subscription_credits, topup_credits,
                credits_used, status, created_at, last_used_at, environment,
                subscription_status, period_start, period_end,
                stripe_customer_id, stripe_subscription_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_id) DO UPDATE SET
                key_hash=excluded.key_hash,
                label=excluded.label,
                plan=excluded.plan,
                subscription_credits=excluded.subscription_credits,
                topup_credits=excluded.topup_credits,
                credits_used=excluded.credits_used,
                status=excluded.status,
                last_used_at=excluded.last_used_at,
                environment=excluded.environment,
                subscription_status=excluded.subscription_status,
                period_start=excluded.period_start,
                period_end=excluded.period_end,
                stripe_customer_id=excluded.stripe_customer_id,
                stripe_subscription_id=excluded.stripe_subscription_id
            """,
            (
                key.public_id, key.key_hash, key.label, key.plan,
                key.subscription_credits, key.topup_credits, key.credits_used,
                key.status.value if isinstance(key.status, KeyStatus) else key.status,
                key.created_at, key.last_used_at, key.environment,
                key.subscription_status.value
                if isinstance(key.subscription_status, SubscriptionStatus)
                else key.subscription_status,
                key.period_start, key.period_end,
                key.stripe_customer_id, key.stripe_subscription_id,
            ),
        )

    @staticmethod
    def _row_to_key(row) -> 'AccessKey':
        return AccessKey.from_dict(dict(row))

    @staticmethod
    def _ledger(conn, key: 'AccessKey', delta: int, bucket: str, reason: str) -> None:
        conn.execute(
            """INSERT INTO credit_ledger
               (public_id, delta, bucket, reason, balance_after, at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key.public_id, delta, bucket, reason, key.credits_remaining,
             datetime.now().isoformat()),
        )

    @staticmethod
    def _rolled(key: 'AccessKey', now: Optional[str] = None) -> 'AccessKey':
        """
        Apply any billing periods that have elapsed since we last looked.

        Renewal is lazy rather than a cron job: a subscription that nobody
        touches for three months should show this month's allowance, not three
        months of it. So the allowance is *reset*, never accumulated, and the
        period is advanced to whichever one contains `now`.

        A canceled or past-due subscription rolls its period but grants
        nothing, which is what stops a lapsed customer refilling for free.
        """
        if not key.period_end:
            return key
        now = now or datetime.now().isoformat()
        if now < key.period_end:
            return key

        period_start, period_end = key.period_start, key.period_end
        # Skip forward however many periods have passed, in one step.
        while period_end <= now:
            period_start, period_end = period_end, _add_month(period_end)

        renews = key.subscription_status == SubscriptionStatus.ACTIVE
        key.subscription_credits = plan_allowance(key.plan) if renews else 0
        key.period_start, key.period_end = period_start, period_end
        if not renews and key.subscription_status == SubscriptionStatus.CANCELED:
            key.subscription_status = SubscriptionStatus.NONE
        return key

    @classmethod
    def _fetch(cls, conn, public_id: str) -> Optional['AccessKey']:
        row = conn.execute(
            "SELECT * FROM access_keys WHERE public_id = ?", (public_id,)
        ).fetchone()
        return cls._row_to_key(row) if row else None

    # ---- issuing -------------------------------------------------------

    @classmethod
    def issue(
        cls,
        label: str,
        plan: str = "starter",
        credits: int = 0,
        environment: str = "live",
        subscribe: bool = False,
    ) -> Dict[str, Any]:
        """
        Mint a new key.

        Returns a dict containing `key` — the plaintext, shown only here — plus
        the stored record. Persist or hand over the plaintext immediately; it
        cannot be recovered.
        """
        if credits < 0:
            raise ValueError("credits cannot be negative")

        public_id = secrets.token_hex(PUBLIC_ID_BYTES)
        secret = secrets.token_hex(SECRET_BYTES)
        plaintext = f"{KEY_PREFIX}_{environment}_{public_id}{secret}"

        now = datetime.now().isoformat()
        subscribed = plan in PLANS and plan_allowance(plan) > 0 and subscribe

        record = AccessKey(
            public_id=public_id,
            key_hash=_hash_key(plaintext),
            label=label,
            plan=plan,
            # A bare `credits=` grant is treated as bought outright, so it
            # cannot evaporate at the next rollover.
            subscription_credits=plan_allowance(plan) if subscribed else 0,
            topup_credits=credits,
            environment=environment,
            subscription_status=(
                SubscriptionStatus.ACTIVE if subscribed else SubscriptionStatus.NONE
            ),
            period_start=now if subscribed else None,
            period_end=_add_month(now) if subscribed else None,
        )

        with cls._connect(write=True) as conn:
            cls._upsert(conn, record)
            cls._ledger(conn, record, record.credits_remaining, "issue",
                        f"issued on {plan}")

        logger.info(
            f"Issued access key {public_id} ({plan}, "
            f"{record.credits_remaining} credits)"
        )
        return {"key": plaintext, "record": record.to_public_dict()}

    # ---- verification --------------------------------------------------

    @classmethod
    def verify(cls, plaintext: Optional[str]) -> Optional[AccessKey]:
        """
        Resolve a presented key to its record.

        Returns None for anything not currently usable: malformed, unknown,
        or revoked. A zero balance still verifies — the caller decides whether
        the balance covers the work.
        """
        public_id = parse_key(plaintext or "")
        if not public_id:
            return None

        with cls._connect() as conn:
            record = cls._fetch(conn, public_id)

        if record is not None:
            # Show the rolled balance. The database catches up on the next
            # write; reads do not need a transaction to be truthful.
            record = cls._rolled(record)

        if record is None:
            return None
        # Constant-time: a timing signal here would leak the secret
        if not hmac.compare_digest(record.key_hash, _hash_key(plaintext)):
            return None
        if record.status != KeyStatus.ACTIVE:
            return None
        return record

    # ---- metering ------------------------------------------------------

    @classmethod
    def charge(cls, public_id: str, credits: int, reason: str = "") -> AccessKey:
        """
        Deduct credits, atomically.

        Read-modify-write happens under the lock so two concurrent requests
        cannot both spend the last credit.

        Raises:
            KeyError: no such key
            InsufficientCredits: balance will not cover it
        """
        if credits < 0:
            raise ValueError("cannot charge a negative amount")

        # BEGIN IMMEDIATE: the read and the write are one transaction, so a
        # second process cannot squeeze between them and spend the same credit.
        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            if record.status != KeyStatus.ACTIVE:
                raise KeyError(f"access key is not active: {public_id}")

            # Roll the period before checking the balance, so a customer whose
            # allowance renewed while they were away is not told they are broke.
            record = cls._rolled(record)

            if record.credits_remaining < credits:
                raise InsufficientCredits(credits, record.credits_remaining)

            # Spend the bucket that expires first. Draining permanent top-ups
            # while the monthly allowance quietly expired would take money from
            # the customer and give nothing back.
            from_subscription = min(record.subscription_credits, credits)
            from_topup = credits - from_subscription
            record.subscription_credits -= from_subscription
            record.topup_credits -= from_topup

            record.credits_used += credits
            record.last_used_at = datetime.now().isoformat()
            cls._upsert(conn, record)
            cls._ledger(conn, record, -credits, "charge", reason)

        logger.info(
            f"Charged {credits} credits to {public_id}"
            f"{f' for {reason}' if reason else ''}; {record.credits_remaining} left"
        )
        return record

    @classmethod
    def refund(cls, public_id: str, credits: int, reason: str = "") -> AccessKey:
        """Give credits back when a charged operation failed before doing work."""
        if credits < 0:
            raise ValueError("cannot refund a negative amount")

        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            record = cls._rolled(record)
            # Refunds land in the permanent bucket. Returning them to an
            # allowance that expires tonight would be a refund in name only.
            record.topup_credits += credits
            record.credits_used = max(0, record.credits_used - credits)
            cls._upsert(conn, record)
            cls._ledger(conn, record, credits, "refund", reason)

        logger.info(
            f"Refunded {credits} credits to {public_id}"
            f"{f' after {reason}' if reason else ''}"
        )
        return record

    @classmethod
    def top_up(cls, public_id: str, credits: int) -> AccessKey:
        """Add purchased credits to an existing key."""
        return cls.add_topup(public_id, credits)


    # ---- subscriptions -------------------------------------------------

    @classmethod
    def start_subscription(
        cls,
        public_id: str,
        plan: str,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
    ) -> AccessKey:
        """
        Put a key on a plan and grant this period's allowance.

        Raises:
            KeyError: no such key
            ValueError: unknown plan
        """
        if plan not in PLANS:
            raise ValueError(f"Unknown plan: {plan}. Choose from {', '.join(PLANS)}.")

        now = datetime.now().isoformat()
        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")

            record.plan = plan
            record.subscription_status = SubscriptionStatus.ACTIVE
            record.subscription_credits = plan_allowance(plan)
            record.period_start = now
            record.period_end = _add_month(now)
            if stripe_customer_id:
                record.stripe_customer_id = stripe_customer_id
            if stripe_subscription_id:
                record.stripe_subscription_id = stripe_subscription_id

            cls._upsert(conn, record)
            cls._ledger(conn, record, plan_allowance(plan), "subscription",
                        f"started {plan}")

        logger.info(f"{public_id} subscribed to {plan}")
        return record

    @classmethod
    def renew_subscription(cls, public_id: str) -> AccessKey:
        """
        Refresh the allowance for a new billing period.

        Called when Stripe confirms a renewal payment. The allowance is set,
        never added to: an unused month does not stack onto the next one, which
        is what "monthly allowance" means to everyone who has ever had one.
        """
        now = datetime.now().isoformat()
        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")

            record.subscription_status = SubscriptionStatus.ACTIVE
            record.subscription_credits = plan_allowance(record.plan)
            record.period_start = now
            record.period_end = _add_month(now)
            cls._upsert(conn, record)
            cls._ledger(conn, record, plan_allowance(record.plan),
                        "subscription", "renewed")

        logger.info(f"{public_id} renewed on {record.plan}")
        return record

    @classmethod
    def set_subscription_status(
        cls, public_id: str, status: SubscriptionStatus
    ) -> AccessKey:
        """
        Mark a subscription past due or canceled.

        Neither touches top-up credits. A customer who bought 2,000 credits
        outright keeps them when their card fails; taking those away would be
        keeping money for nothing.
        """
        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")

            record.subscription_status = status
            if status in (SubscriptionStatus.PAST_DUE, SubscriptionStatus.NONE):
                # Stop the allowance now; the top-up bucket is untouched.
                record.subscription_credits = 0
            cls._upsert(conn, record)
            cls._ledger(conn, record, 0, "subscription", f"status -> {status.value}")

        logger.info(f"{public_id} subscription is now {status.value}")
        return record

    @classmethod
    def add_topup(cls, public_id: str, credits: int, reason: str = "top-up") -> AccessKey:
        """Add purchased credits that never expire."""
        if credits <= 0:
            raise ValueError("a top-up must be positive")

        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            record = cls._rolled(record)
            record.topup_credits += credits
            cls._upsert(conn, record)
            cls._ledger(conn, record, credits, "topup", reason)

        logger.info(f"{public_id} topped up {credits}; {record.credits_remaining} total")
        return record

    @classmethod
    def find_by_stripe_subscription(cls, subscription_id: str) -> Optional[AccessKey]:
        with cls._connect() as conn:
            row = conn.execute(
                "SELECT * FROM access_keys WHERE stripe_subscription_id = ?",
                (subscription_id,),
            ).fetchone()
        return cls._row_to_key(row) if row else None

    @classmethod
    def find_by_stripe_customer(cls, customer_id: str) -> Optional[AccessKey]:
        with cls._connect() as conn:
            row = conn.execute(
                "SELECT * FROM access_keys WHERE stripe_customer_id = ?",
                (customer_id,),
            ).fetchone()
        return cls._row_to_key(row) if row else None

    @classmethod
    def ledger(cls, public_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Every credit movement, newest first."""
        with cls._connect() as conn:
            rows = conn.execute(
                """SELECT delta, bucket, reason, balance_after, at
                   FROM credit_ledger WHERE public_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (public_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- administration ------------------------------------------------

    @classmethod
    def revoke(cls, public_id: str) -> AccessKey:
        with cls._connect(write=True) as conn:
            record = cls._fetch(conn, public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            record.status = KeyStatus.REVOKED
            cls._upsert(conn, record)
        logger.info(f"Revoked access key {public_id}")
        return record

    @classmethod
    def get(cls, public_id: str) -> Optional[AccessKey]:
        with cls._connect() as conn:
            record = cls._fetch(conn, public_id)
        return cls._rolled(record) if record else None

    @classmethod
    def list_keys(cls) -> List[Dict[str, Any]]:
        with cls._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM access_keys ORDER BY created_at DESC"
            ).fetchall()
        return [cls._rolled(cls._row_to_key(r)).to_public_dict() for r in rows]
