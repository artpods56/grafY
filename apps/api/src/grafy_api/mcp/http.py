"""The `/mcp` endpoint: a PAT gate in front of FastMCP's Streamable HTTP app.

The gate decides who is calling before the MCP server reads a byte of the body:
exactly one Workspace personal access token, no browser session. A cookie is ambient
authority a cross-site page could ride, and the MCP surface has no CSRF token to stop
it, so a request that carries the session cookie is refused rather than ignored.

Tools never act with what the gate learned. They call the REST API in process with
the same bearer header (see ``grafy_api.mcp.context``), so each call is authorized
again by the route that serves it.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import HTTPException
from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from grafy_api.app_state import get_identity
from grafy_api.auth import SESSION_COOKIE

MCP_PATH: Final = "/mcp"
PRINCIPAL_STATE_KEY: Final = "grafy_mcp_principal"
# FastMCP's Starlette app replaces ``scope["app"]`` with itself, so the gate keeps
# the API app it was reached through for the tools' in-process client.
API_APP_STATE_KEY: Final = "grafy_mcp_api_app"
# The largest JSON-RPC body the endpoint reads. Tool arguments are graph specs and
# command batches, never file bytes of any size.
MAX_MCP_REQUEST_BYTES: Final = 4 * 1024 * 1024


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        {"detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _too_large() -> JSONResponse:
    return JSONResponse(
        {"detail": f"MCP request bodies are limited to {MAX_MCP_REQUEST_BYTES} bytes"},
        status_code=413,
    )


async def _bounded_body(receive: Receive) -> bytes | None:
    """The whole request body, or ``None`` once it passes the limit."""

    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_MCP_REQUEST_BYTES:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    sent = False

    async def replayed() -> Message:
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replayed


class McpEndpoint:
    """ASGI app for ``/mcp``, live only while the API lifespan runs it."""

    def __init__(self, server: FastMCP) -> None:
        self._server = server
        self._app: StarletteWithLifespan | None = None

    @asynccontextmanager
    async def serving(self) -> AsyncGenerator[None]:
        """Run one FastMCP HTTP app for one API lifespan.

        Its session manager runs once, so every lifespan builds its own app.
        Stateless with JSON responses: every request is authenticated on its own and
        no session outlives it. Host and Origin checks guard ambient credentials;
        this endpoint refuses them, and it answers on whatever public host the
        gateway forwards.
        """

        app = self._server.http_app(
            path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            host_origin_protection=False,
        )
        async with app.lifespan(app):
            self._app = app
            try:
                yield
            finally:
                self._app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        response = await self._admit(request)
        if response is not None:
            await response(scope, receive, send)
            return
        app = self._app
        if app is None:
            await JSONResponse({"detail": "MCP is not serving"}, status_code=503)(
                scope, receive, send
            )
            return
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_MCP_REQUEST_BYTES:
            await _too_large()(scope, receive, send)
            return
        body = await _bounded_body(receive)
        if body is None:
            await _too_large()(scope, receive, send)
            return
        await app(scope, _replay(body, receive), send)

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
        state = request.scope.setdefault("state", {})
        state[PRINCIPAL_STATE_KEY] = principal
        state[API_APP_STATE_KEY] = request.app
        return None


__all__ = [
    "API_APP_STATE_KEY",
    "MAX_MCP_REQUEST_BYTES",
    "MCP_PATH",
    "PRINCIPAL_STATE_KEY",
    "McpEndpoint",
]
