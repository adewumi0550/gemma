-- Tokenic schema for Postgres / Cloud SQL.
--   psql "$DATABASE_URL" -f tokenic_mcp/schema.sql

CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    key_hash     TEXT NOT NULL UNIQUE,   -- SHA-256; the raw key is never stored
    prefix       TEXT NOT NULL,          -- e.g. 'tk_live_a1b2c3…' for display
    owner        TEXT NOT NULL,
    email        TEXT,
    label        TEXT,
    created_at   DOUBLE PRECISION NOT NULL,
    revoked_at   DOUBLE PRECISION,       -- NULL = active
    token_quota  BIGINT,                 -- NULL = unlimited
    tokens_used  BIGINT NOT NULL DEFAULT 0,
    requests     BIGINT NOT NULL DEFAULT 0,
    tool_calls   BIGINT NOT NULL DEFAULT 0
);

-- Hit on every authenticated request, so it must be indexed.
CREATE INDEX IF NOT EXISTS idx_api_keys_hash  ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys (owner);

CREATE TABLE IF NOT EXISTS usage_events (
    id                TEXT PRIMARY KEY,
    key_id            TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    ts                DOUBLE PRECISION NOT NULL,
    model             TEXT NOT NULL DEFAULT '',
    endpoint          TEXT NOT NULL DEFAULT '',
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0,
    llm_calls         INTEGER NOT NULL DEFAULT 0,
    tool_calls        INTEGER NOT NULL DEFAULT 0,
    seconds           DOUBLE PRECISION NOT NULL DEFAULT 0,
    ok                BOOLEAN NOT NULL DEFAULT TRUE,
    error             TEXT
);

CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON usage_events (key_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_usage_ts     ON usage_events (ts DESC);

-- Monthly billing rollup.
CREATE OR REPLACE VIEW usage_monthly AS
SELECT k.owner,
       k.id  AS key_id,
       date_trunc('month', to_timestamp(u.ts)) AS month,
       COUNT(*)                  AS requests,
       SUM(u.prompt_tokens)      AS prompt_tokens,
       SUM(u.completion_tokens)  AS completion_tokens,
       SUM(u.total_tokens)       AS total_tokens,
       SUM(u.tool_calls)         AS tool_calls
  FROM usage_events u
  JOIN api_keys k ON k.id = u.key_id
 GROUP BY k.owner, k.id, month
 ORDER BY month DESC;
