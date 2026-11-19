"""The MCP surface: Streamable HTTP at ``/mcp``, PAT-only, served through the REST API.

See ``docs/adr/0023-mcp-is-a-pat-only-adapter-over-the-rest-api.md``.
"""

from grafy_api.mcp.http import MCP_PATH, McpEndpoint
from grafy_api.mcp.server import build_mcp_server

__all__ = ["MCP_PATH", "McpEndpoint", "build_mcp_server"]
