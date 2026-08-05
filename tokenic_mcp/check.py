"""Verify a storage backend before you rely on it.

    python -m tokenic_mcp.check

Reads config from the environment, falling back to tokenic_mcp/.env. Connects,
creates the schema if missing, then does a full round trip — issue a key,
meter usage, read it back, enforce a quota — and cleans up after itself.

Run this before a workshop. Discovering your database is unreachable while
thirty people watch is a bad way to find out.
"""

from __future__ import annotations

import os
import pathlib
import sys

ENV_FILE = pathlib.Path(__file__).parent / ".env"


def load_env_file() -> list[str]:
    """Minimal .env loader. Real env vars always win."""
    loaded = []
    if not ENV_FILE.exists():
        return loaded
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def mask(url: str) -> str:
    """Hide the password so this is safe to paste into a bug report."""
    if "://" not in url:
        return url
    scheme, _, rest = url.partition("://")
    if "@" not in rest:
        return url
    creds, _, host = rest.partition("@")
    user = creds.split(":")[0]
    return f"{scheme}://{user}:****@{host}"


def ok(msg: str) -> None:
    print(f"\033[32m ok \033[0m {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"\033[31mfail\033[0m {msg}")
    if hint:
        for line in hint.strip().splitlines():
            print(f"       {line}")


def apply_schema(dsn: str) -> bool:
    import psycopg

    ddl = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    try:
        with psycopg.connect(dsn, connect_timeout=15) as conn:
            conn.execute(ddl)
            conn.commit()
        ok("schema applied (api_keys, usage_events, usage_monthly)")
        return True
    except Exception as exc:
        fail(f"could not apply schema: {exc}")
        return False


def check_postgres() -> bool:
    dsn = os.getenv("DATABASE_URL") or os.getenv("MCP_DB") or ""
    source = "DATABASE_URL" if os.getenv("DATABASE_URL") else "MCP_DB"
    if not dsn:
        fail(
            "no connection string found (DATABASE_URL or MCP_DB)",
            """
Set it one of three ways:

  export MCP_DB='postgresql://user:pass@host:5432/dbname'

  echo "MCP_DB=postgresql://..." >> tokenic_mcp/.env

  gcloud run deploy ... --set-env-vars MCP_DB='postgresql://...'
""",
        )
        return False

    print(f"     {source} = {mask(dsn)}")

    try:
        import psycopg  # noqa: F401
        import psycopg_pool  # noqa: F401
    except ImportError:
        fail(
            "postgres driver missing",
            'pip install "psycopg[binary]" psycopg-pool',
        )
        return False
    ok("driver installed")

    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=15) as conn:
            row = conn.execute("select current_database(), current_user").fetchone()
        ok(f"connected — database '{row[0]}' as '{row[1]}'")
    except Exception as exc:
        name = type(exc).__name__
        hint = ""
        if "timeout" in name.lower() or "timeout" in str(exc).lower():
            hint = """
Timed out. Usually one of:
  - Cloud SQL 'Authorized networks' does not include your IP
    console.cloud.google.com -> SQL -> Connections -> Networking
  - a firewall between you and port 5432
  - from Cloud Run, use the unix socket instead of a public IP:
    DATABASE_URL='postgresql://user:pass@/db?host=/cloudsql/PROJECT:REGION:INSTANCE'
"""
        elif "password" in str(exc).lower() or "authentication" in str(exc).lower():
            hint = """
Authentication failed. If your password contains @ : / ? # or $,
URL-encode it — $ becomes %24, @ becomes %40.
  python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" 'your-password'
"""
        fail(f"{name}: {str(exc)[:200]}", hint)
        return False

    return apply_schema(dsn)


def round_trip() -> bool:
    """Prove the backend actually works, not just that it connects."""
    from tokenic_mcp import metering
    from tokenic_mcp.storage import get_storage

    try:
        issued = metering.create_key(
            owner="__selftest__", label="tokenic self-test", token_quota=1000
        )
        key_id = issued["id"]
        ok(f"issued a key — quota {issued['token_quota']:,}")

        metering.authenticate(issued["api_key"])
        ok("authenticated with the raw key")

        metering.record(key_id, {"prompt": 400, "completion": 50, "total": 450},
                        model="selftest", endpoint="/check")
        usage = metering.usage_for(key_id)
        assert usage["total_tokens"] == 450, usage
        ok(f"recorded usage — {usage['total_tokens']} tokens, "
           f"{usage['quota']['remaining']} remaining")

        metering.record(key_id, {"prompt": 600, "completion": 40, "total": 640},
                        model="selftest", endpoint="/check")
        try:
            metering.authenticate(issued["api_key"])
            fail("quota was NOT enforced — key still works past its limit")
            return False
        except metering.QuotaError:
            ok("quota enforced once exhausted")

        # Clean up so self-tests don't accumulate in a real database.
        store = get_storage()
        store.revoke_key(key_id)
        if hasattr(store, "pool"):  # postgres
            with store.pool.connection() as conn:
                conn.execute("DELETE FROM usage_events WHERE key_id = %s", (key_id,))
                conn.execute("DELETE FROM api_keys WHERE id = %s", (key_id,))
        ok("cleaned up test data")
        return True

    except Exception as exc:
        fail(f"round trip failed: {type(exc).__name__}: {str(exc)[:200]}")
        return False


def main() -> int:
    loaded = load_env_file()
    print("\n\033[1m==> tokenic storage check\033[0m")
    if loaded:
        print(f"     loaded {len(loaded)} setting(s) from tokenic_mcp/.env")

    backend = os.getenv("TOKENIC_BACKEND", "memory").lower()
    print(f"     backend: {backend}\n")

    if backend in ("postgres", "postgresql", "cloudsql"):
        if not check_postgres():
            return 1
    elif backend == "firestore":
        try:
            from google.cloud import firestore  # noqa: F401
        except ImportError:
            fail("firestore driver missing", "pip install google-cloud-firestore")
            return 1
        ok("driver installed")
        if not os.getenv("GOOGLE_CLOUD_PROJECT"):
            print("     note: GOOGLE_CLOUD_PROJECT unset; relying on ADC default")
    else:
        print("     memory backend — nothing to connect to.")
        print("     Set TOKENIC_BACKEND=postgres or =firestore to test a real one.\n")

    print()
    if not round_trip():
        return 1

    quota = os.getenv("TOKENIC_DEFAULT_QUOTA", "2000000")
    print(f"\n\033[32mReady.\033[0m New keys will be issued with {int(quota):,} tokens.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
