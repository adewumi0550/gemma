"""FastAPI glue — authenticate a request by API key, then meter what it used.

Wire it into the agent in two lines:

    from tokenic_mcp.middleware import require_key, meter

    @app.post("/chat")
    def chat(ask: Ask, key = Depends(require_key)):
        result = run_agent(ask.message)
        meter(key, result, model=MODEL, endpoint="/chat")
        return result

Auth is opt-in. With TOKENIC_REQUIRE_KEY unset, `require_key` returns None and
the agent stays open — so a workshop can run without anyone provisioning keys.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException

from tokenic_mcp import metering
from tokenic_mcp.models import ApiKey

REQUIRE_KEY = os.getenv("TOKENIC_REQUIRE_KEY", "").lower() in ("1", "true", "yes")


def require_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKey | None:
    """Resolve the caller's API key.

    Accepts either `Authorization: Bearer tk_live_…` or `X-API-Key: tk_live_…`.
    Returns None when auth is disabled, so the same handler works both ways.
    """
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()

    if not raw:
        if REQUIRE_KEY:
            raise HTTPException(
                status_code=401,
                detail="missing API key — send 'Authorization: Bearer tk_live_…'",
            )
        return None

    try:
        return metering.authenticate(raw)
    except metering.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except metering.QuotaError as exc:
        # 429 rather than 403: the key is valid, it has simply run out.
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def meter(key: ApiKey | None, result: dict, model: str = "", endpoint: str = "") -> None:
    """Record what a call consumed.

    No-ops for unauthenticated calls. Never raises — a metering outage must not
    take down the agent, so failures are logged and swallowed.
    """
    if key is None:
        return
    try:
        answer = result.get("answer", "")
        failed = isinstance(answer, str) and answer.startswith("Error:")
        metering.record(
            key_id=key.id,
            usage=result.get("usage", {}),
            model=model,
            endpoint=endpoint,
            ok=not failed,
            error=answer if failed else None,
        )
    except Exception as exc:  # noqa: BLE001 - metering must never break serving
        import logging

        logging.getLogger(__name__).warning("usage not recorded: %s", exc)
