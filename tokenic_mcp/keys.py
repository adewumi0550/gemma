"""API key generation and verification.

Two rules, both non-negotiable:

1. The raw key is shown exactly once, at creation, and never stored.
2. Lookup is by SHA-256 hash, so a database leak does not leak usable keys.

SHA-256 rather than bcrypt/argon2 is deliberate here. Those are for *passwords*,
which are low-entropy and human-chosen. These keys carry 256 bits of entropy
from `secrets`, so brute force is not the threat model — and we need lookup to
be a fast, constant-cost hash on every single request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

# tk = tokenic. The environment marker makes it obvious in logs and support
# tickets whether someone is holding a production or test key.
PREFIXES = {"live": "tk_live_", "test": "tk_test_"}

PREFIX_DISPLAY_LEN = 16


def generate(environment: str = "live") -> tuple[str, str, str, str]:
    """Mint a new key.

    Returns (key_id, raw_key, key_hash, display_prefix).
    `raw_key` is the only time the secret exists — hand it to the user and
    drop it.
    """
    if environment not in PREFIXES:
        raise ValueError(f"environment must be one of {list(PREFIXES)}")

    raw = PREFIXES[environment] + secrets.token_urlsafe(32)
    return (
        f"key_{uuid.uuid4().hex[:16]}",
        raw,
        hash_key(raw),
        raw[:PREFIX_DISPLAY_LEN] + "…",
    )


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def looks_like_key(candidate: str) -> bool:
    """Cheap shape check so we don't hash obvious junk."""
    return any(candidate.startswith(p) for p in PREFIXES.values())


def verify(raw_key: str, expected_hash: str) -> bool:
    """Constant-time comparison — avoids leaking prefix matches via timing."""
    return hmac.compare_digest(hash_key(raw_key), expected_hash)
