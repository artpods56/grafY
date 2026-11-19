"""The `/mcp` endpoint: a PAT gate in front of the MCP SDK's Streamable HTTP manager.

The gate decides who is calling before the SDK reads a byte of the body: exactly one
Workspace personal access token, no browser session. A cookie is ambient authority a
cross-site page could ride, and the MCP surface has no CSRF token to stop it, so a
request that carries the session cookie is refused rather than ignored.

Tools never act with what the gate learned. They call the REST API in process with
the same bearer header (see ``grafy_api.mcp.server``), so each call is authorized again
by the route that serves it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import HTTPException
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from grafy_api.app_state import get_identity
from grafy_api.auth import SESSION_COOKIE

MCP_PATH: Final = "/mcp"
PRINCIPAL_STATE_KEY: Final = "grafy_mcp_principal"
# The largest JSON-RPC body the endpoint reads. Tool arguments are graph specs and
# command batches, never file bytes of any size.
MAX_MCP_REQUEST_BYTES: Final = 4 * 1024 * 1024


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


class McpEndpoint:
    """ASGI app for ``/mcp``, live only while the API lifespan runs it."""

    def __init__(self, server: MCPServer) -> None:
        self._server = server
        self._manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def serving(self) -> AsyncIterator[None]:
        """Run one session manager for one API lifespan.

        A manager runs once, so every lifespan builds its own. Stateless: every
        request is authenticated on its own and no session outlives it. DNS
        rebinding protection guards ambient credentials; this endpoint refuses them,
        and it answers on whatever public host the gateway forwards.
        """

        _ = self._server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            max_request_body_size=MAX_MCP_REQUEST_BYTES,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
        manager = self._server.session_manager
        async with manager.run():
            self._manager = manager
            try:
                yield
            finally:
                self._manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        response = await self._admit(request)
        if response is not None:
            await response(scope, receive, send)
            return
        manager = self._manager
        if manager is None:
            await JSONResponse({"detail": "MCP is not serving"}, status_code=503)(
                scope, receive, send
            )
            return
        await manager.handle_request(scope, receive, send)

    async def _admit(self, request: Request) -> JSONResponse | None:
        auth = get_identity(request.app).auth_service
        if SESSION_COOKIE in request.cookies:
            await auth.audit_unauthenticated_failure(
                operation="auth.mcp.verify",
                error_code="cookie_rejected",
            )
            return _unauthorized("MCP accepts a bearer personal access token only")
        authorization = request.headers.get("authorization")
        if authorization is None:
            await auth.audit_unauthenticated_failure(
                operation="auth.mcp.verify",
                error_code="authentication_required",
            )
            return _unauthorized("Authentication required")
        try:
            principal = await auth.require_workspace_pat_principal(
                request, authorization
            )
        except HTTPException:
            await auth.audit_unauthenticated_failure(
                operation="auth.mcp.verify",
                error_code="authentication_required",
            )
            return _unauthorized("Authentication required")
        request.scope.setdefault("state", {})[PRINCIPAL_STATE_KEY] = principal
        return None


__all__ = ["MAX_MCP_REQUEST_BYTES", "MCP_PATH", "PRINCIPAL_STATE_KEY", "McpEndpoint"]
