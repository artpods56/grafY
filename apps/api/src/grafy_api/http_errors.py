import os
import time
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4
from dataclasses import dataclass

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from grafy_api.app_state import get_identity
from grafy_api.diagnostics import (
    DiagnosticContext,
    diagnostic_scope,
    record_failure,
)
from grafy_api.v1.routes.auth.services import AuthService
from grafy_core.domain.errors import (
    CapabilityDeniedError,
    Failure,
    FailureKind,
    FailureSpec,
    GrafyCoreError,
    IdentityInvariantError,
    NotFoundError,
    UserDisabledError,
)


logger = structlog.get_logger(__name__)

_REQUEST_VALIDATION_SPEC = FailureSpec(
    code="request.validation_failed",
    kind=FailureKind.VALIDATION,
    public_message="Request validation failed",
)
_HTTP_CAPACITY_SPEC = FailureSpec(
    code="http.capacity_exceeded",
    kind=FailureKind.CAPACITY,
    public_message="Request capacity exceeded",
)
_HTTP_UNAVAILABLE_SPEC = FailureSpec(
    code="http.unavailable",
    kind=FailureKind.UNAVAILABLE,
    public_message="Service unavailable",
)
_INTERNAL_FAILURE_SPEC = FailureSpec(
    code="internal.unexpected_error",
    kind=FailureKind.INTERNAL,
    public_message="An internal error occurred",
)

_FAILURE_STATUS = {
    FailureKind.VALIDATION: 422,
    FailureKind.UNAUTHENTICATED: 401,
    FailureKind.FORBIDDEN: 403,
    FailureKind.NOT_FOUND: 404,
    FailureKind.CONFLICT: 409,
    FailureKind.CAPACITY: 429,
    FailureKind.UNAVAILABLE: 503,
    FailureKind.INTERNAL: 500,
}


def _failure_response(failure: Failure, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": failure.message,
            "code": failure.code,
            "error_id": str(failure.error_id),
        },
    )


@dataclass(frozen=True)
class WorkspaceFailureRoute:
    operation: str
    resource_type: str | None = None
    resource_path_param: str | None = None


_WORKSPACE_FAILURE_ROUTES: dict[str, WorkspaceFailureRoute] = {
    "list_workspaces": WorkspaceFailureRoute(
        operation="workspace.list",
        resource_type="workspace",
    ),
    "create_workspace": WorkspaceFailureRoute(
        operation="workspace.create",
        resource_type="workspace",
    ),
    "list_members": WorkspaceFailureRoute(
        operation="workspace.membership.list",
        resource_type="workspace_membership",
    ),
    "resolve_invitation_candidate": WorkspaceFailureRoute(
        operation="workspace.invitation.candidate.resolve",
        resource_type="user",
    ),
    "create_workspace_invitation": WorkspaceFailureRoute(
        operation="workspace.invitation.create",
        resource_type="workspace_invitation",
    ),
    "list_workspace_invitations": WorkspaceFailureRoute(
        operation="workspace.invitation.list",
        resource_type="workspace_invitation",
    ),
    "cancel_workspace_invitation": WorkspaceFailureRoute(
        operation="workspace.invitation.cancel",
        resource_type="workspace_invitation",
        resource_path_param="invitation_id",
    ),
    "change_member_role": WorkspaceFailureRoute(
        operation="workspace.membership.role_change",
        resource_type="user",
        resource_path_param="user_id",
    ),
    "remove_member": WorkspaceFailureRoute(
        operation="workspace.membership.remove",
        resource_type="user",
        resource_path_param="user_id",
    ),
    "list_personal_access_tokens": WorkspaceFailureRoute(
        operation="credential.pat.list",
        resource_type="personal_access_token",
    ),
    "create_personal_access_token": WorkspaceFailureRoute(
        operation="credential.pat.create",
        resource_type="personal_access_token",
    ),
    "revoke_personal_access_token": WorkspaceFailureRoute(
        operation="credential.pat.revoke",
        resource_type="personal_access_token",
        resource_path_param="token_id",
    ),
    "list_graph_folders": WorkspaceFailureRoute(
        operation="graph.folder.list",
        resource_type="graph_folder",
    ),
    "create_graph_folder": WorkspaceFailureRoute(
        operation="graph.folder.create",
        resource_type="graph_folder",
    ),
    "rename_graph_folder": WorkspaceFailureRoute(
        operation="graph.folder.rename",
        resource_type="graph_folder",
        resource_path_param="folder_id",
    ),
    "delete_graph_folder": WorkspaceFailureRoute(
        operation="graph.folder.delete",
        resource_type="graph_folder",
        resource_path_param="folder_id",
    ),
    "assign_graph_folder": WorkspaceFailureRoute(
        operation="graph.folder.assign",
        resource_type="saved_graph",
        resource_path_param="graph_id",
    ),
    "archive_graph": WorkspaceFailureRoute(
        operation="graph.archive",
        resource_type="saved_graph",
        resource_path_param="graph_id",
    ),
    "restore_graph": WorkspaceFailureRoute(
        operation="graph.restore",
        resource_type="saved_graph",
        resource_path_param="graph_id",
    ),
    "star_graph": WorkspaceFailureRoute(
        operation="graph.star",
        resource_type="saved_graph",
        resource_path_param="graph_id",
    ),
    "unstar_graph": WorkspaceFailureRoute(
        operation="graph.unstar",
        resource_type="saved_graph",
        resource_path_param="graph_id",
    ),
    "record_graph_open": WorkspaceFailureRoute(
        operation="graph.open.record",
        resource_type="saved_graph",
        resource_path_param="graph_id",
    ),
}


def workspace_failure_metadata(
    request: Request,
) -> tuple[str, UUID | None, str | None, str | None] | None:
    route = request.scope.get("route")
    route_name = getattr(route, "name", None)
    if not isinstance(route_name, str):
        return None
    failure_route = _WORKSPACE_FAILURE_ROUTES.get(route_name)
    if failure_route is None:
        return None

    workspace_id: UUID | None = None
    raw_workspace_id = request.path_params.get("workspace_id")
    if isinstance(raw_workspace_id, str):
        try:
            workspace_id = UUID(raw_workspace_id)
        except ValueError:
            workspace_id = None

    resource_id: str | None = None
    if failure_route.resource_path_param is not None:
        raw_resource_id = request.path_params.get(failure_route.resource_path_param)
        if isinstance(raw_resource_id, str):
            try:
                resource_id = str(UUID(raw_resource_id))
            except ValueError:
                resource_id = None
    return (
        failure_route.operation,
        workspace_id,
        failure_route.resource_type,
        resource_id,
    )


async def _audit_workspace_failure(request: Request, error_code: str) -> None:
    if getattr(request.state, "auth_failure_audited", False):
        return
    metadata = workspace_failure_metadata(request)
    if metadata is None:
        return
    operation, workspace_id, resource_type, resource_id = metadata
    await get_identity(request.app).auth_service.audit_request_failure(
        request,
        operation=operation,
        error_code=error_code,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )


async def _audit_auth_failure(request: Request, error_code: str) -> None:
    if getattr(request.state, "auth_failure_audited", False):
        return
    if request.url.path.startswith("/v1/auth/") and not request.url.path.endswith(
        ("/oidc/login", "/oidc/callback")
    ):
        await get_identity(request.app).auth_service.audit_request_failure(
            request,
            operation="auth.session.request",
            error_code=error_code,
        )


async def _request_validation_error_handler(
    request: Request,
    exception: Exception,
) -> Response:
    if not isinstance(exception, RequestValidationError):
        raise exception

    redacted_errors = [
        {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        for error in exception.errors()
    ]
    is_oidc_callback = request.url.path.endswith("/auth/oidc/callback")
    is_oidc_login = request.url.path.endswith("/auth/oidc/login")

    if is_oidc_login:
        login_auth: AuthService = get_identity(request.app).auth_service
        abuse_keys = login_auth.browser_abuse_keys(request)
        allowed = await login_auth.allow_login_start(
            abuse_keys.browser_key,
            abuse_keys.network_key,
        )
        spec = _REQUEST_VALIDATION_SPEC if allowed else _HTTP_CAPACITY_SPEC
        failure = record_failure(
            exception,
            operation="http.request.validate" if allowed else "http.request.limit",
            spec=spec,
        )
        with diagnostic_scope(
            DiagnosticContext(primary_error_id=failure.error_id),
        ):
            await login_auth.audit_request_failure(
                request,
                operation="oidc.login.start",
                error_code="validation_failed" if allowed else "rate_limited",
            )
        return JSONResponse(
            status_code=422 if allowed else 429,
            content={
                "detail": redacted_errors if allowed else "Too many login attempts",
                "code": failure.code,
                "error_id": str(failure.error_id),
            },
        )

    if is_oidc_callback:
        auth: AuthService = get_identity(request.app).auth_service
        allowed = await auth.cleanup_malformed_callback(request)
        spec = _REQUEST_VALIDATION_SPEC if allowed else _HTTP_CAPACITY_SPEC
        failure = record_failure(
            exception,
            operation="http.request.validate" if allowed else "http.request.limit",
            spec=spec,
        )
        error_code = "validation_failed" if allowed else "rate_limited"
        with diagnostic_scope(
            DiagnosticContext(primary_error_id=failure.error_id),
        ):
            await auth.audit_request_failure(
                request,
                operation="oidc.login.callback",
                error_code=error_code,
            )
        response = JSONResponse(
            status_code=422 if allowed else 429,
            content={
                "detail": redacted_errors if allowed else "Too many callback attempts",
                "code": failure.code,
                "error_id": str(failure.error_id),
            },
        )
        auth.clear_transaction_cookie(response)
        return response

    failure = record_failure(
        exception,
        operation="http.request.validate",
        spec=_REQUEST_VALIDATION_SPEC,
    )
    with diagnostic_scope(
        DiagnosticContext(primary_error_id=failure.error_id),
    ):
        await _audit_workspace_failure(request, "validation_failed")

    return JSONResponse(
        status_code=422,
        content={
            "detail": redacted_errors,
            "code": failure.code,
            "error_id": str(failure.error_id),
        },
    )


async def _grafy_core_error_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, GrafyCoreError):
        raise exception
    spec = exception.failure_spec
    if spec is None:
        raise exception

    failure = record_failure(
        exception,
        operation="http.request.handle",
    )
    if isinstance(exception, NotFoundError):
        audit_code = "not_found"
    elif isinstance(exception, CapabilityDeniedError):
        audit_code = "capability_denied"
    elif isinstance(exception, UserDisabledError):
        audit_code = "disabled_user"
    elif isinstance(exception, IdentityInvariantError):
        audit_code = "identity_invariant"
    else:
        audit_code = failure.code

    with diagnostic_scope(
        DiagnosticContext(primary_error_id=failure.error_id),
    ):
        await _audit_workspace_failure(request, audit_code)
        if isinstance(exception, NotFoundError):
            await _audit_auth_failure(request, audit_code)

    return _failure_response(
        failure,
        status_code=_FAILURE_STATUS[spec.kind],
    )


async def _http_error_handler(request: Request, exception: Exception) -> Response:
    if not isinstance(exception, HTTPException):
        raise exception

    error_code = "not_found" if exception.status_code == 404 else "http_error"
    if exception.status_code < 500:
        await _audit_workspace_failure(request, error_code)
        await _audit_auth_failure(request, error_code)
        return await http_exception_handler(request, exception)

    if exception.status_code == 503:
        spec = _HTTP_UNAVAILABLE_SPEC
    else:
        spec = _INTERNAL_FAILURE_SPEC
    failure = record_failure(
        exception,
        operation="http.request.reject",
        spec=spec,
    )
    with diagnostic_scope(
        DiagnosticContext(primary_error_id=failure.error_id),
    ):
        await _audit_workspace_failure(request, error_code)
        await _audit_auth_failure(request, error_code)
    response = _failure_response(
        failure,
        status_code=exception.status_code,
    )
    if exception.headers is not None:
        response.headers.update(exception.headers)
    return response


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if isinstance(route, BaseRoute):
        path = getattr(route, "path", None)
        if isinstance(path, str):
            return path
    return "unmatched"


async def _http_diagnostics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = uuid4()
    request.state.request_id = request_id
    started_at = time.perf_counter()

    with diagnostic_scope(
        DiagnosticContext(request_id=request_id),
        inherit=False,
    ):
        try:
            response = await call_next(request)
        except Exception as exception:
            failure = record_failure(
                exception,
                operation="http.request.handle",
                spec=_INTERNAL_FAILURE_SPEC,
            )
            response = _failure_response(failure, status_code=500)

        response.headers["X-Request-ID"] = str(request_id)
        duration_ms = (time.perf_counter() - started_at) * 1_000
        try:
            logger.info(
                "http_request_completed",
                method=request.method,
                route=_route_template(request),
                status_code=response.status_code,
                duration_ms=round(duration_ms, 3),
            )
        except Exception:
            try:
                os.write(2, b"grafy diagnostics: request completion logging failed\n")
            except OSError:
                pass
        return response


def register_http_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        RequestValidationError,
        _request_validation_error_handler,
    )
    app.add_exception_handler(HTTPException, _http_error_handler)
    app.add_exception_handler(GrafyCoreError, _grafy_core_error_handler)
    app.middleware("http")(_http_diagnostics_middleware)


__all__ = ["register_http_error_handlers"]
