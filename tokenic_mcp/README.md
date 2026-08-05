# tokenic_mcp

API keys and per-user token metering for the Gemma agent — exposed as **MCP tools**,
backed by **Firestore** or **Postgres/Cloud SQL**.

The agent answers questions. This decides *who is allowed to ask* and *what it cost*.

---

## The flow

```
1. Deploy Gemma 4 on Cloud Run           ./deploy.sh PROJECT all
2. Issue keys via MCP                    issue_api_key(owner="ada")   ──┐
3. User calls the agent with their key   Authorization: Bearer tk_…    │
4. Every call is metered per key         tokens, tools, latency  ──────┤
5. Query usage via MCP                   get_usage / top_consumers  ◄──┘
```

Steps 2 and 5 are MCP tools, so an agent can administer the platform — issue a
key, check a quota, see who's overspending — by *calling tools*, not by you
running SQL.

---

## Quick start (zero setup)

```bash
pip install -r tokenic_mcp/requirements.txt
```

```bash
python -m tokenic_mcp.server
```

Defaults to in-memory storage — no Firebase project, no database. Perfect for a
workshop. Everything is lost on restart, which is the point.

---

## The 9 MCP tools

**Key management**

| Tool | Does |
|---|---|
| `issue_api_key(owner, email, label, token_quota, environment)` | Mint a key. Returns the raw secret **once** |
| `revoke_api_key(key_id)` | Kill a key immediately |
| `list_api_keys(owner)` | List keys — never returns secrets |
| `describe_api_key(key_id)` | One key's quota and totals |

**Usage metering**

| Tool | Does |
|---|---|
| `get_usage(key_id, days)` | Tokens for one key, with quota state |
| `get_total_usage(days)` | Aggregate across all keys |
| `recent_calls(key_id, limit)` | Raw event log, newest first |
| `top_consumers(limit)` | Rank keys by tokens burned |
| `check_quota(key_id)` | Can this key still run? |

---

## Storage backends

Pick with `TOKENIC_BACKEND`:

| Value | Use when |
|---|---|
| `memory` *(default)* | Workshops, local dev, tests. No setup |
| `firestore` | You want serverless — matches Cloud Run, no pool to manage |
| `postgres` | You want SQL aggregation for billing |

### Firebase / Firestore

```bash
pip install google-cloud-firestore && gcloud firestore databases create --location=us-central1
```

```bash
TOKENIC_BACKEND=firestore GOOGLE_CLOUD_PROJECT=your-project python -m tokenic_mcp.server
```

Counters use `Increment`, so concurrent requests can't clobber each other's totals.

### Postgres / Cloud SQL

```bash
pip install "psycopg[binary]" psycopg-pool
```

```bash
psql "$DATABASE_URL" -f tokenic_mcp/schema.sql
```

```bash
TOKENIC_BACKEND=postgres DATABASE_URL=postgresql://user:pass@host/tokenic python -m tokenic_mcp.server
```

From Cloud Run, connect over the unix socket and add the instance at deploy time:

```bash
gcloud run deploy gemma-agent --source . --add-cloudsql-instances PROJECT:REGION:INSTANCE --set-env-vars TOKENIC_BACKEND=postgres,DATABASE_URL='postgresql://user:pass@/tokenic?host=/cloudsql/PROJECT:REGION:INSTANCE'
```

**Which one?** Firestore if you just want it to work with no ops. Postgres if
you'll bill from this data — `schema.sql` ships a `usage_monthly` view that
rolls up tokens per owner per month in one query.

---

## Turning on auth in the agent

Off by default. To require keys:

```bash
TOKENIC_REQUIRE_KEY=true TOKENIC_BACKEND=firestore python app.py
```

Then calls need a key:

```bash
curl -X POST localhost:8080/chat -H "Authorization: Bearer tk_live_YOUR_KEY" -H 'Content-Type: application/json' -d '{"message":"Weather in Lagos?"}'
```

The response gains a `billed_to` block:

```json
{
  "answer": "It's 25.6°C in Lagos…",
  "usage": {"prompt": 1847, "completion": 96, "total": 1943, "tool_calls": 2},
  "billed_to": {"key_id": "key_a1b2…", "owner": "ada", "tokens_remaining": 3057}
}
```

Status codes: **401** for a bad or revoked key, **429** when the quota is gone.

---

## Security

- **Raw keys are never stored.** Only SHA-256. A database dump leaks no usable keys.
- **Shown once**, at creation. There is no "reveal key" endpoint — by design.
- **Constant-time comparison** on verify, so timing can't leak a prefix match.
- **256 bits of entropy** from `secrets`.

SHA-256 rather than bcrypt is deliberate: bcrypt exists for low-entropy
human-chosen passwords. These keys are high-entropy random, so brute force isn't
the threat, and verification runs on every request and must stay cheap.

**Metering never breaks serving.** If the database is down, `meter()` logs and
swallows the error — you lose a usage record, not the user's request. That
tradeoff is intentional; flip it if you'd rather fail closed on billing.

---

## Connect to Claude Desktop

```json
{
  "mcpServers": {
    "tokenic": {
      "command": "python",
      "args": ["-m", "tokenic_mcp.server"],
      "env": {"TOKENIC_BACKEND": "firestore", "GOOGLE_CLOUD_PROJECT": "your-project"}
    }
  }
}
```

Then just ask: *"Issue an API key for Ada with a 10,000 token quota"* or
*"Who used the most tokens this week?"*

---

## Running as two servers

Once issuing needs tighter access control than reading usage, split them:

```bash
TOKENIC_TOOLSET=keys python -m tokenic_mcp.server
```

```bash
TOKENIC_TOOLSET=usage python -m tokenic_mcp.server
```

Same code, two processes, two access boundaries.

---

## Files

```
models.py       ApiKey and UsageEvent
keys.py         generation, hashing, constant-time verify
metering.py     lifecycle + metering logic
server.py       the MCP server (9 tools)
middleware.py   FastAPI auth dependency + meter()
schema.sql      Postgres DDL + monthly rollup view
storage/
  base.py       the interface everything else talks to
  memory.py     dev/test
  firestore.py  Firebase
  postgres.py   Cloud SQL
```
