"""Backtest engine MCP server."""
from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server

from src.mcp_server.tools import register_tools

app = Server("backtest-engine")
register_tools(app)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    # Pre-initialize the worker pool BEFORE asyncio.run() so that fork() is
    # called from a single-threaded context.  After asyncio starts, the event
    # loop creates internal threads; forking from a multi-threaded process risks
    # deadlocks in the child (Python 3.12 raises a DeprecationWarning for this).
    # Warming up the pool here means every subsequent MCP tool call gets workers
    # that are already alive — no spawn overhead during request handling.
    from src.mcp_server.facade import _get_worker_pool
    _get_worker_pool()

    asyncio.run(main())
