"""The storage contract.

Everything above this line (metering, MCP tools, middleware) talks only to
this interface, so swapping Firestore for Cloud SQL is a config change.
"""

from __future__ import annotations

from typing import Protocol

from tokenic_mcp.models import ApiKey, UsageEvent


class Storage(Protocol):
    # --- keys ---
    def put_key(self, key: ApiKey) -> None: ...

    def get_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """Hot path — called on every authenticated request. Index this column."""

    def get_key(self, key_id: str) -> ApiKey | None: ...

    def list_keys(self, owner: str | None = None) -> list[ApiKey]: ...

    def revoke_key(self, key_id: str) -> bool: ...

    # --- usage ---
    def record_usage(self, event: UsageEvent) -> None:
        """Append the event AND increment the key's running totals."""

    def list_usage(self, key_id: str | None = None, since: float | None = None,
                   limit: int = 100) -> list[UsageEvent]: ...

    def summarise(self, key_id: str | None = None, since: float | None = None) -> dict: ...

    def close(self) -> None: ...
