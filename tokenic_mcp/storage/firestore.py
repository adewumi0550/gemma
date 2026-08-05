"""Firestore backend (Firebase).

Good default for this project: serverless like Cloud Run, no instance to keep
warm, no connection pool, and the free tier covers a workshop comfortably.

Layout:
    api_keys/{key_id}           the key document
    usage/{event_id}            one document per metered call

The counters on the key document are updated with Increment, which is atomic
server-side — two concurrent requests can't clobber each other's totals.

Setup:
    pip install google-cloud-firestore
    gcloud firestore databases create --location=us-central1
"""

from __future__ import annotations

import os

from tokenic_mcp.models import ApiKey, UsageEvent

KEYS = "api_keys"
USAGE = "usage"


class FirestoreStorage:
    def __init__(self, project: str | None = None, database: str | None = None) -> None:
        from google.cloud import firestore  # imported late so the dep stays optional

        self._firestore = firestore
        kwargs = {}
        if project or os.getenv("GOOGLE_CLOUD_PROJECT"):
            kwargs["project"] = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        if database or os.getenv("FIRESTORE_DATABASE"):
            kwargs["database"] = database or os.getenv("FIRESTORE_DATABASE")
        self.db = firestore.Client(**kwargs)

    # --- keys ---

    def put_key(self, key: ApiKey) -> None:
        self.db.collection(KEYS).document(key.id).set(key.to_dict())

    def get_key_by_hash(self, key_hash: str) -> ApiKey | None:
        # Firestore auto-indexes single fields, so this equality filter is fast.
        hits = (
            self.db.collection(KEYS)
            .where(filter=self._firestore.FieldFilter("key_hash", "==", key_hash))
            .limit(1)
            .stream()
        )
        for doc in hits:
            return ApiKey.from_dict(doc.to_dict())
        return None

    def get_key(self, key_id: str) -> ApiKey | None:
        doc = self.db.collection(KEYS).document(key_id).get()
        return ApiKey.from_dict(doc.to_dict()) if doc.exists else None

    def list_keys(self, owner: str | None = None) -> list[ApiKey]:
        query = self.db.collection(KEYS)
        if owner:
            query = query.where(filter=self._firestore.FieldFilter("owner", "==", owner))
        return [ApiKey.from_dict(d.to_dict()) for d in query.stream()]

    def revoke_key(self, key_id: str) -> bool:
        import time

        ref = self.db.collection(KEYS).document(key_id)
        snapshot = ref.get()
        if not snapshot.exists or snapshot.to_dict().get("revoked_at") is not None:
            return False
        ref.update({"revoked_at": time.time()})
        return True

    # --- usage ---

    def record_usage(self, event: UsageEvent) -> None:
        self.db.collection(USAGE).document(event.id).set(event.to_dict())
        # Atomic server-side increments; safe under concurrency.
        self.db.collection(KEYS).document(event.key_id).update(
            {
                "tokens_used": self._firestore.Increment(event.total_tokens),
                "requests": self._firestore.Increment(1),
                "tool_calls": self._firestore.Increment(event.tool_calls),
            }
        )

    def list_usage(self, key_id: str | None = None, since: float | None = None,
                   limit: int = 100) -> list[UsageEvent]:
        query = self.db.collection(USAGE)
        if key_id:
            query = query.where(filter=self._firestore.FieldFilter("key_id", "==", key_id))
        if since:
            query = query.where(filter=self._firestore.FieldFilter("ts", ">=", since))
        query = query.order_by("ts", direction=self._firestore.Query.DESCENDING).limit(limit)
        return [UsageEvent.from_dict(d.to_dict()) for d in query.stream()]

    def summarise(self, key_id: str | None = None, since: float | None = None) -> dict:
        # Firestore has no SUM aggregation across arbitrary filters here, so we
        # fold client-side. Fine at workshop scale; for real volume, keep
        # rolled-up daily counters instead of scanning raw events.
        rows = self.list_usage(key_id, since, limit=10_000)
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
