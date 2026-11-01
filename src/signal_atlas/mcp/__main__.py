"""
__main__.py - CLI Entrypoint for Signal Atlas MCP Server.

Supports running over stdio (Claude Desktop, IDEs) or SSE (ChatGPT, Web clients, Tunnels).
"""

import argparse
import sys
from signal_atlas.mcp.server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal Atlas MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport protocol (stdio for Claude Desktop, sse for Web/ChatGPT)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind for SSE transport (default: 8000)",
    )

    args = parser.parse_args()

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        # Allow tunnel hostnames like ngrok or cloudflare when running in SSE mode
        if hasattr(mcp.settings, "transport_security") and mcp.settings.transport_security:
            mcp.settings.transport_security.enable_dns_rebinding_protection = False
        print(f"Starting Signal Atlas FastMCP SSE server on http://{args.host}:{args.port}/sse", file=sys.stderr)
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
