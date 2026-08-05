"""In-memory backend — for local development, workshops and tests.

Everything vanishes on restart. That is the point: participants can try the
whole flow with zero setup, no Firebase project and no database.
"""

from __future__ import annotations

import threading

from tokenic_mcp.models import ApiKey, UsageEvent


class MemoryStorage:
    def __init__(self) -> None:
        self._keys: dict[str, ApiKey] = {}
        self._by_hash: dict[str, str] = {}
        self._usage: list[UsageEvent] = []
        self._lock = threading.Lock()

    # --- keys ---

    def put_key(self, key: ApiKey) -> None:
        with self._lock:
            self._keys[key.id] = key
            self._by_hash[key.key_hash] = key.id

    def get_key_by_hash(self, key_hash: str) -> ApiKey | None:
        key_id = self._by_hash.get(key_hash)
        return self._keys.get(key_id) if key_id else None

    def get_key(self, key_id: str) -> ApiKey | None:
        return self._keys.get(key_id)

    def list_keys(self, owner: str | None = None) -> list[ApiKey]:
        keys = list(self._keys.values())
        if owner:
            keys = [k for k in keys if k.owner == owner]
        return sorted(keys, key=lambda k: k.created_at, reverse=True)

    def revoke_key(self, key_id: str) -> bool:
        import time

        with self._lock:
            key = self._keys.get(key_id)
            if key is None or key.revoked_at is not None:
                return False
            key.revoked_at = time.time()
            return True

    # --- usage ---

    def record_usage(self, event: UsageEvent) -> None:
        with self._lock:
            self._usage.append(event)
            key = self._keys.get(event.key_id)
            if key:
                key.tokens_used += event.total_tokens
                key.requests += 1
                key.tool_calls += event.tool_calls

    def list_usage(self, key_id: str | None = None, since: float | None = None,
                   limit: int = 100) -> list[UsageEvent]:
        rows = self._usage
        if key_id:
            rows = [e for e in rows if e.key_id == key_id]
        if since:
            rows = [e for e in rows if e.ts >= since]
        return sorted(rows, key=lambda e: e.ts, reverse=True)[:limit]

    def summarise(self, key_id: str | None = None, since: float | None = None) -> dict:
        rows = self.list_usage(key_id, since, limit=10**9)
        by_model: dict[str, int] = {}
        for e in rows:
            by_model[e.model] = by_model.get(e.model, 0) + e.total_tokens
        return {
            "requests": len(rows),
            "prompt_tokens": sum(e.prompt_tokens for e in rows),
            "completion_tokens": sum(e.completion_tokens for e in rows),
            "total_tokens": sum(e.total_tokens for e in rows),
            "llm_calls": sum(e.llm_calls for e in rows),
            "tool_calls": sum(e.tool_calls for e in rows),
            "errors": sum(1 for e in rows if not e.ok),
            "seconds": round(sum(e.seconds for e in rows), 2),
            "by_model": by_model,
        }

    def close(self) -> None:
        pass
