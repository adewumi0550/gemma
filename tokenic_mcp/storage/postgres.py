"""Postgres backend (Cloud SQL, Supabase, Neon, or plain local Postgres).

Pick this over Firestore when you want SQL aggregation for billing — summing
tokens per key per month is one query here, versus scanning documents.

Two connection styles:

  Direct URL (local, Supabase, Neon, or Cloud SQL with a public IP):
      DATABASE_URL=postgresql://user:pass@host:5432/tokenic

  Cloud SQL from Cloud Run, over the built-in unix socket:
      DATABASE_URL=postgresql://user:pass@/tokenic?host=/cloudsql/PROJECT:REGION:INSTANCE
      ...and deploy with --add-cloudsql-instances PROJECT:REGION:INSTANCE

Setup:
    pip install "psycopg[binary]"
    psql "$DATABASE_URL" -f tokenic_mcp/schema.sql
"""

from __future__ import annotations

import os

from tokenic_mcp.models import ApiKey, UsageEvent


class PostgresStorage:
    def __init__(self, dsn: str | None = None) -> None:
        import psycopg  # late import keeps the dep optional
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self._psycopg = psycopg
        dsn = dsn or os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")

        # A pool matters on Cloud Run: each instance handles concurrent
        # requests, and opening a Postgres connection per request is slow.
        self.pool = ConnectionPool(dsn, min_size=1, max_size=5, kwargs={"row_factory": dict_row})

    # --- keys ---

    def put_key(self, key: ApiKey) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (id, key_hash, prefix, owner, email, label,
                                      created_at, revoked_at, token_quota,
                                      tokens_used, requests, tool_calls)
                VALUES (%(id)s, %(key_hash)s, %(prefix)s, %(owner)s, %(email)s, %(label)s,
                        %(created_at)s, %(revoked_at)s, %(token_quota)s,
                        %(tokens_used)s, %(requests)s, %(tool_calls)s)
                ON CONFLICT (id) DO UPDATE SET
                    revoked_at  = EXCLUDED.revoked_at,
                    token_quota = EXCLUDED.token_quota,
                    label       = EXCLUDED.label
                """,
                key.to_dict(),
            )

    def get_key_by_hash(self, key_hash: str) -> ApiKey | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = %s", (key_hash,)
            ).fetchone()
        return ApiKey.from_dict(row) if row else None

    def get_key(self, key_id: str) -> ApiKey | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE id = %s", (key_id,)).fetchone()
        return ApiKey.from_dict(row) if row else None

    def list_keys(self, owner: str | None = None) -> list[ApiKey]:
        sql = "SELECT * FROM api_keys"
        params: tuple = ()
        if owner:
            sql += " WHERE owner = %s"
            params = (owner,)
        sql += " ORDER BY created_at DESC"
        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ApiKey.from_dict(r) for r in rows]

    def revoke_key(self, key_id: str) -> bool:
        import time

        with self.pool.connection() as conn:
            result = conn.execute(
                "UPDATE api_keys SET revoked_at = %s WHERE id = %s AND revoked_at IS NULL",
                (time.time(), key_id),
            )
        return result.rowcount > 0

    # --- usage ---

    def record_usage(self, event: UsageEvent) -> None:
        # Both statements in one transaction: never bill for an event we
        # failed to store, never store an event we failed to bill for.
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO usage_events (id, key_id, ts, model, endpoint,
                                          prompt_tokens, completion_tokens, total_tokens,
                                          llm_calls, tool_calls, seconds, ok, error)
                VALUES (%(id)s, %(key_id)s, %(ts)s, %(model)s, %(endpoint)s,
                        %(prompt_tokens)s, %(completion_tokens)s, %(total_tokens)s,
                        %(llm_calls)s, %(tool_calls)s, %(seconds)s, %(ok)s, %(error)s)
                """,
                event.to_dict(),
            )
            conn.execute(
                """
                UPDATE api_keys
                   SET tokens_used = tokens_used + %s,
                       requests    = requests + 1,
                       tool_calls  = tool_calls + %s
                 WHERE id = %s
                """,
                (event.total_tokens, event.tool_calls, event.key_id),
            )

    def list_usage(self, key_id: str | None = None, since: float | None = None,
                   limit: int = 100) -> list[UsageEvent]:
        sql = "SELECT * FROM usage_events WHERE TRUE"
        params: list = []
        if key_id:
            sql += " AND key_id = %s"
            params.append(key_id)
        if since:
            sql += " AND ts >= %s"
            params.append(since)
        sql += " ORDER BY ts DESC LIMIT %s"
        params.append(limit)
        with self.pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [UsageEvent.from_dict(r) for r in rows]

    def summarise(self, key_id: str | None = None, since: float | None = None) -> dict:
        # This is the reason to choose Postgres: aggregation happens in the
        # database, not by pulling every row into Python.
        where, params = "WHERE TRUE", []
        if key_id:
            where += " AND key_id = %s"
            params.append(key_id)
        if since:
            where += " AND ts >= %s"
            params.append(since)

        with self.pool.connection() as conn:
            totals = conn.execute(
                f"""
                SELECT COUNT(*)                          AS requests,
                       COALESCE(SUM(prompt_tokens),0)    AS prompt_tokens,
                       COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                       COALESCE(SUM(total_tokens),0)     AS total_tokens,
                       COALESCE(SUM(llm_calls),0)        AS llm_calls,
                       COALESCE(SUM(tool_calls),0)       AS tool_calls,
                       COALESCE(SUM(seconds),0)          AS seconds,
                       COUNT(*) FILTER (WHERE NOT ok)    AS errors
                  FROM usage_events {where}
                """,
                params,
            ).fetchone()
            by_model = conn.execute(
                f"SELECT model, SUM(total_tokens) AS t FROM usage_events {where} GROUP BY model",
                params,
            ).fetchall()

        out = dict(totals)
        out["seconds"] = round(float(out["seconds"]), 2)
        out["by_model"] = {r["model"]: int(r["t"]) for r in by_model}
        return out

    def close(self) -> None:
        self.pool.close()
