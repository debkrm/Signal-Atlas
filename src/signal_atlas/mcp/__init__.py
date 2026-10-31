"""
signal_atlas.mcp - Model Context Protocol interface adapter for Signal Atlas.
"""

from signal_atlas.mcp.models import MCPResponseEnvelope
from signal_atlas.mcp.server import mcp, run_stdio

__all__ = ["mcp", "run_stdio", "MCPResponseEnvelope"]
