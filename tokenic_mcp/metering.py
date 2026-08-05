"""Key lifecycle and usage metering — the logic the MCP tools and the API share."""

from __future__ import annotations

import os
import time
import uuid

from tokenic_mcp import keys as keylib
from tokenic_mcp.models import ApiKey, UsageEvent
from tokenic_mcp.storage import get_storage

# Tokens every new key gets unless told otherwise. 2000K = 2,000,000.
# Set TOKENIC_DEFAULT_QUOTA=0 to issue unlimited keys instead.
DEFAULT_TOKEN_QUOTA = int(os.getenv("TOKENIC_DEFAULT_QUOTA", "2000000"))


class AuthError(Exception):
    """Key missing, malformed, unknown or revoked."""


class QuotaError(Exception):
    """Key is valid but out of tokens."""


# --- keys ------------------------------------------------------------------


def create_key(owner: str, email: str | None = None, label: str | None = None,
               token_quota: int | None = None, environment: str = "live") -> dict:
    """Mint a key. The raw secret is in the return value and nowhere else.

    Omitting token_quota applies DEFAULT_TOKEN_QUOTA (2,000,000 tokens).
    Pass 0 explicitly for an unlimited key.
    """
    if token_quota is None:
        token_quota = DEFAULT_TOKEN_QUOTA or None
    elif token_quota == 0:
        token_quota = None  # explicit unlimited

    key_id, raw, key_hash, prefix = keylib.generate(environment)
    record = ApiKey(
        id=key_id, key_hash=key_hash, prefix=prefix,
        owner=owner, email=email, label=label, token_quota=token_quota,
    )
    get_storage().put_key(record)
    return {
        "api_key": raw,  # shown once
        "warning": "Copy this now — it is hashed on save and cannot be shown again.",
        **record.public(),
    }


def revoke_key(key_id: str) -> dict:
    done = get_storage().revoke_key(key_id)
    return {"revoked": done, "key_id": key_id,
            "detail": None if done else "not found, or already revoked"}


def list_keys(owner: str | None = None) -> list[dict]:
    return [k.public() for k in get_storage().list_keys(owner)]


def get_key(key_id: str) -> dict | None:
    key = get_storage().get_key(key_id)
    return key.public() if key else None


# --- auth ------------------------------------------------------------------


def authenticate(raw_key: str) -> ApiKey:
    """Resolve a raw key to its record, or raise.

    Raises AuthError for unusable keys and QuotaError when the key is fine but
    exhausted — the caller maps those to 401 and 429 respectively.
    """
    if not raw_key or not keylib.looks_like_key(raw_key):
        raise AuthError("malformed API key")

    key = get_storage().get_key_by_hash(keylib.hash_key(raw_key))
    if key is None:
        raise AuthError("unknown API key")
    if not key.active:
        raise AuthError("API key has been revoked")
    if key.over_quota:
        raise QuotaError(
            f"token quota exhausted ({key.tokens_used}/{key.token_quota})"
        )
    return key


# --- usage -----------------------------------------------------------------


def record(key_id: str, usage: dict, model: str = "", endpoint: str = "",
           ok: bool = True, error: str | None = None) -> UsageEvent:
    """Store one metered call and roll its tokens onto the key.

    `usage` is the dict the agent already returns, so the agent needs no new
    bookkeeping — it just hands over what it measured.
    """
    event = UsageEvent(
        id=f"evt_{uuid.uuid4().hex[:20]}",
        key_id=key_id,
        model=model,
        endpoint=endpoint,
        prompt_tokens=int(usage.get("prompt", usage.get("prompt_tokens", 0)) or 0),
        completion_tokens=int(usage.get("completion", usage.get("completion_tokens", 0)) or 0),
        total_tokens=int(usage.get("total", usage.get("total_tokens", 0)) or 0),
        llm_calls=int(usage.get("llm_calls", 0) or 0),
        tool_calls=int(usage.get("tool_calls", 0) or 0),
        seconds=float(usage.get("seconds", 0) or 0),
        ok=ok,
        error=error,
    )
    get_storage().record_usage(event)
    return event


def usage_for(key_id: str, days: int | None = None) -> dict:
    since = time.time() - days * 86400 if days else None
    summary = get_storage().summarise(key_id=key_id, since=since)
    key = get_storage().get_key(key_id)
    if key:
        summary["quota"] = {
            "limit": key.token_quota,
            "used": key.tokens_used,
            "remaining": key.tokens_remaining,
            "exhausted": key.over_quota,
        }
    if days:
        summary["window_days"] = days
    return summary


def usage_all(days: int | None = None) -> dict:
    since = time.time() - days * 86400 if days else None
    summary = get_storage().summarise(since=since)
    summary["keys"] = len(get_storage().list_keys())
    if days:
        summary["window_days"] = days
    return summary


def recent_events(key_id: str | None = None, limit: int = 20) -> list[dict]:
    return [e.to_dict() for e in get_storage().list_usage(key_id=key_id, limit=limit)]


def top_consumers(limit: int = 10) -> list[dict]:
    """Who is burning the most tokens — the first question you ask in production."""
    ranked = sorted(get_storage().list_keys(), key=lambda k: k.tokens_used, reverse=True)
    return [
        {
            "key_id": k.id, "owner": k.owner, "prefix": k.prefix,
            "tokens_used": k.tokens_used, "requests": k.requests,
            "quota": k.token_quota, "active": k.active,
        }
        for k in ranked[:limit]
    ]
