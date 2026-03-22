"""Entry point for `python -m src.mcp_server`."""
from src.mcp_server.server import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
