"""Tokenic MCP server — key issuing and usage metering as MCP tools.

Two toolsets in one server:

    keys   : issue_api_key, revoke_api_key, list_api_keys, describe_api_key
    usage  : get_usage, get_total_usage, recent_calls, top_consumers, check_quota

Run it:
    TOKENIC_BACKEND=firestore python -m tokenic_mcp.server          # stdio
    TOKENIC_BACKEND=postgres  python -m tokenic_mcp.server --http   # HTTP/SSE

Point an MCP client at it — Claude Desktop, an ADK agent via MCPToolset, or
anything else that speaks MCP:

    {
      "mcpServers": {
        "tokenic": {
          "command": "python",
          "args": ["-m", "tokenic_mcp.server"],
          "env": {"TOKENIC_BACKEND": "firestore"}
        }
      }
    }

To split this into two servers (issuing vs. metering) — which is the right move
once issuing needs tighter access control than reading usage — set
TOKENIC_TOOLSET=keys or TOKENIC_TOOLSET=usage and run two processes.
"""

from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP

from tokenic_mcp import metering

TOOLSET = os.getenv("TOKENIC_TOOLSET", "all").lower()

mcp = FastMCP("tokenic")


# --- key management --------------------------------------------------------

if TOOLSET in ("all", "keys"):

    @mcp.tool()
    def issue_api_key(owner: str, email: str = "", label: str = "",
                      token_quota: int = 0, environment: str = "live") -> dict:
        """Issue a new API key for a user.

        The raw key is returned ONCE and never stored — only its SHA-256 hash
        is kept, so it cannot be recovered later. Pass token_quota=0 for
        unlimited, or a token count to cap usage.

        Args:
            owner: who the key belongs to, e.g. a username or org id
            email: optional contact address
            label: optional note, e.g. "workshop demo"
            token_quota: maximum total tokens; 0 means unlimited
            environment: "live" or "test"
        """
        return metering.create_key(
            owner=owner,
            email=email or None,
            label=label or None,
            token_quota=token_quota or None,
            environment=environment,
        )

    @mcp.tool()
    def revoke_api_key(key_id: str) -> dict:
        """Permanently revoke an API key. Takes effect on the next request."""
        return metering.revoke_key(key_id)

    @mcp.tool()
    def list_api_keys(owner: str = "") -> list[dict]:
        """List issued keys, optionally filtered to one owner.

        Never returns the secret — only the display prefix and usage totals.
        """
        return metering.list_keys(owner or None)

    @mcp.tool()
    def describe_api_key(key_id: str) -> dict:
        """Get one key's details, quota and running totals."""
        return metering.get_key(key_id) or {"error": f"no such key: {key_id}"}


# --- usage metering --------------------------------------------------------

if TOOLSET in ("all", "usage"):

    @mcp.tool()
    def get_usage(key_id: str, days: int = 0) -> dict:
        """Token usage for one key: totals, per-model breakdown and quota state.

        Args:
            key_id: the key to report on
            days: restrict to the last N days; 0 means all time
        """
        return metering.usage_for(key_id, days or None)

    @mcp.tool()
    def get_total_usage(days: int = 0) -> dict:
        """Aggregate usage across every key. Use for overall cost tracking."""
        return metering.usage_all(days or None)

    @mcp.tool()
    def recent_calls(key_id: str = "", limit: int = 20) -> list[dict]:
        """The most recent metered calls, newest first. Useful for debugging."""
        return metering.recent_events(key_id or None, limit)

    @mcp.tool()
    def top_consumers(limit: int = 10) -> list[dict]:
        """Rank keys by tokens consumed — who is spending your budget."""
        return metering.top_consumers(limit)

    @mcp.tool()
    def check_quota(key_id: str) -> dict:
        """Check whether a key still has tokens left before you let it run."""
        key = metering.get_key(key_id)
        if not key:
            return {"error": f"no such key: {key_id}"}
        return {
            "key_id": key_id,
            "active": key["active"],
            "quota": key["token_quota"],
            "used": key["tokens_used"],
            "remaining": key["tokens_remaining"],
            "allowed": key["active"] and not (
                key["token_quota"] and key["tokens_used"] >= key["token_quota"]
            ),
        }


def main() -> None:
    transport = "sse" if "--http" in sys.argv else "stdio"
    backend = os.getenv("TOKENIC_BACKEND", "memory")
    # stdout is the MCP channel on stdio — log to stderr or you corrupt it.
    print(f"tokenic mcp · backend={backend} · toolset={TOOLSET} · transport={transport}",
          file=sys.stderr)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
