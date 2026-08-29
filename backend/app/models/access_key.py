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
- Balances are mutated under a lock and persisted with an atomic replace.

Scale note: this is a single-process store, adequate for one Flask server. A
multi-process or multi-host deployment needs a real database with row locking,
otherwise two workers can spend the same credit.
"""

import hashlib
import hmac
import json
import os
import secrets
import threading
import uuid
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
    STORE_FILE = 'access_keys.json'

    _lock = threading.Lock()

    # ---- storage -------------------------------------------------------

    @classmethod
    def _store_path(cls) -> str:
        return os.path.join(cls.STORE_DIR, cls.STORE_FILE)

    @classmethod
    def _load(cls) -> Dict[str, AccessKey]:
        path = cls._store_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Access key store unreadable at {path}: {e}")
            raise
        return {pid: AccessKey.from_dict(d) for pid, d in raw.items()}

    @classmethod
    def _save(cls, keys: Dict[str, AccessKey]) -> None:
        os.makedirs(cls.STORE_DIR, exist_ok=True)
        path = cls._store_path()
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        payload = {pid: k.to_dict() for pid, k in keys.items()}
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            os.chmod(path, 0o600)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

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

        with cls._lock:
            keys = cls._load()
            keys[public_id] = record
            cls._save(keys)

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

        with cls._lock:
            keys = cls._load()
            record = keys.get(public_id)

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

        with cls._lock:
            keys = cls._load()
            record = keys.get(public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            if record.status != KeyStatus.ACTIVE:
                raise KeyError(f"access key is not active: {public_id}")
            if record.credits_remaining < credits:
                raise InsufficientCredits(credits, record.credits_remaining)

            record.credits_remaining -= credits
            record.credits_used += credits
            record.last_used_at = datetime.now().isoformat()
            keys[public_id] = record
            cls._save(keys)

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

        with cls._lock:
            keys = cls._load()
            record = keys.get(public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            record.credits_remaining += credits
            record.credits_used = max(0, record.credits_used - credits)
            keys[public_id] = record
            cls._save(keys)

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
        with cls._lock:
            keys = cls._load()
            record = keys.get(public_id)
            if record is None:
                raise KeyError(f"unknown access key: {public_id}")
            record.status = KeyStatus.REVOKED
            keys[public_id] = record
            cls._save(keys)
        logger.info(f"Revoked access key {public_id}")
        return record

    @classmethod
    def get(cls, public_id: str) -> Optional[AccessKey]:
        with cls._lock:
            return cls._load().get(public_id)

    @classmethod
    def list_keys(cls) -> List[Dict[str, Any]]:
        with cls._lock:
            keys = cls._load()
        return [
            k.to_public_dict()
            for k in sorted(keys.values(), key=lambda x: x.created_at, reverse=True)
        ]
