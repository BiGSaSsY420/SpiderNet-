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


@dataclass
class AccessKey:
    """A sold key. Never holds the plaintext."""
    public_id: str
    key_hash: str
    label: str
    plan: str
    credits_remaining: int
    credits_used: int = 0
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used_at: Optional[str] = None
    environment: str = "live"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, KeyStatus) else self.status
        return d

    def to_public_dict(self) -> Dict[str, Any]:
        """What is safe to show a customer about their own key."""
        return {
            "public_id": self.public_id,
            "label": self.label,
            "plan": self.plan,
            "credits_remaining": self.credits_remaining,
            "credits_used": self.credits_used,
            "status": self.status.value if isinstance(self.status, KeyStatus) else self.status,
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
            credits_remaining=int(data.get("credits_remaining", 0)),
            credits_used=int(data.get("credits_used", 0)),
            status=KeyStatus(status),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_used_at=data.get("last_used_at"),
            environment=data.get("environment", "live"),
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
        credits_remaining INTEGER NOT NULL DEFAULT 0,
        credits_used      INTEGER NOT NULL DEFAULT 0,
        status            TEXT NOT NULL DEFAULT 'active',
        created_at        TEXT NOT NULL,
        last_used_at      TEXT,
        environment       TEXT NOT NULL DEFAULT 'live'
    );
    CREATE INDEX IF NOT EXISTS idx_access_keys_hash ON access_keys(key_hash);
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
                public_id, key_hash, label, plan, credits_remaining,
                credits_used, status, created_at, last_used_at, environment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_id) DO UPDATE SET
                key_hash=excluded.key_hash,
                label=excluded.label,
                plan=excluded.plan,
                credits_remaining=excluded.credits_remaining,
                credits_used=excluded.credits_used,
                status=excluded.status,
                last_used_at=excluded.last_used_at,
                environment=excluded.environment
            """,
            (
                key.public_id, key.key_hash, key.label, key.plan,
                key.credits_remaining, key.credits_used,
                key.status.value if isinstance(key.status, KeyStatus) else key.status,
                key.created_at, key.last_used_at, key.environment,
            ),
        )

    @staticmethod
    def _row_to_key(row) -> 'AccessKey':
        return AccessKey.from_dict(dict(row))

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

        record = AccessKey(
            public_id=public_id,
            key_hash=_hash_key(plaintext),
            label=label,
            plan=plan,
            credits_remaining=credits,
            environment=environment,
        )

        with cls._connect(write=True) as conn:
            cls._upsert(conn, record)

        logger.info(f"Issued access key {public_id} ({plan}, {credits} credits)")
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
            if record.credits_remaining < credits:
                raise InsufficientCredits(credits, record.credits_remaining)

            record.credits_remaining -= credits
            record.credits_used += credits
            record.last_used_at = datetime.now().isoformat()
            cls._upsert(conn, record)

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
            record.credits_remaining += credits
            record.credits_used = max(0, record.credits_used - credits)
            cls._upsert(conn, record)

        logger.info(
            f"Refunded {credits} credits to {public_id}"
            f"{f' after {reason}' if reason else ''}"
        )
        return record

    @classmethod
    def top_up(cls, public_id: str, credits: int) -> AccessKey:
        """Add purchased credits to an existing key."""
        if credits <= 0:
            raise ValueError("top-up must be positive")
        return cls.refund(public_id, credits, reason="top-up")

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
            return cls._fetch(conn, public_id)

    @classmethod
    def list_keys(cls) -> List[Dict[str, Any]]:
        with cls._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM access_keys ORDER BY created_at DESC"
            ).fetchall()
        return [cls._row_to_key(r).to_public_dict() for r in rows]
