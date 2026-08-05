"""Backend selection.

    TOKENIC_BACKEND=memory      default — zero setup, lost on restart
    TOKENIC_BACKEND=firestore   Firebase
    TOKENIC_BACKEND=postgres    Cloud SQL / Supabase / Neon / local
"""

from __future__ import annotations

import os

from tokenic_mcp.storage.base import Storage

_instance: Storage | None = None


def get_storage(backend: str | None = None) -> Storage:
    """Return the process-wide storage singleton."""
    global _instance
    if _instance is not None and backend is None:
        return _instance

    backend = (backend or os.getenv("TOKENIC_BACKEND", "memory")).lower()

    if backend == "memory":
        from tokenic_mcp.storage.memory import MemoryStorage

        _instance = MemoryStorage()
    elif backend == "firestore":
        from tokenic_mcp.storage.firestore import FirestoreStorage

        _instance = FirestoreStorage()
    elif backend in ("postgres", "postgresql", "cloudsql"):
        from tokenic_mcp.storage.postgres import PostgresStorage

        _instance = PostgresStorage()
    else:
        raise ValueError(f"unknown TOKENIC_BACKEND: {backend!r}")

    return _instance


def reset() -> None:
    """Drop the singleton — used by tests."""
    global _instance
    if _instance is not None:
        _instance.close()
    _instance = None


__all__ = ["Storage", "get_storage", "reset"]
