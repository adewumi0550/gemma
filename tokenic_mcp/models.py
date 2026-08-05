"""Data shapes for keys and usage.

Kept as plain dataclasses so the same objects work across Firestore,
Postgres and the in-memory backend without an ORM in the middle.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ApiKey:
    """An issued API key.

    The raw key is NEVER stored — only `key_hash`. `prefix` exists so a user
    can recognise their own key in a list without us keeping the secret.
    """

    id: str
    key_hash: str
    prefix: str
    owner: str
    email: str | None = None
    label: str | None = None
    created_at: float = field(default_factory=time.time)
    revoked_at: float | None = None

    # Quota. None means unlimited.
    token_quota: int | None = None

    # Running totals, denormalised onto the key so a quota check is one read.
    tokens_used: int = 0
    requests: int = 0
    tool_calls: int = 0

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    @property
    def over_quota(self) -> bool:
        return self.token_quota is not None and self.tokens_used >= self.token_quota

    @property
    def tokens_remaining(self) -> int | None:
        if self.token_quota is None:
            return None
        return max(0, self.token_quota - self.tokens_used)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public(self) -> dict[str, Any]:
        """Safe to return over an API — no hash."""
        out = {k: v for k, v in asdict(self).items() if k != "key_hash"}
        out["active"] = self.active
        out["tokens_remaining"] = self.tokens_remaining
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApiKey:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class UsageEvent:
    """One metered call. This is the row you bill from."""

    id: str
    key_id: str
    ts: float = field(default_factory=time.time)

    model: str = ""
    endpoint: str = ""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    llm_calls: int = 0
    tool_calls: int = 0
    seconds: float = 0.0

    ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageEvent:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
