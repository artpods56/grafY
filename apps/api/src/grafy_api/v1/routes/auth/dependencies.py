"""Identity-plane FastAPI dependencies.

These thin resolvers expose the application-lifetime ``AppIdentity`` services
through the standard ``Depends()`` graph, mirroring the workbench plane's
per-service resolvers.  Registering an override for any of the resolver
functions (``identity_service``, ``auth_service``, ``identity_uow_factory``)
replaces that service across every route that consumes it, including
``require_workspace_capability``.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspacePatPrincipal,
)
from grafy_core.ports.identity import IdentityUnitOfWorkPort

from grafy_api.app_state import get_identity
from grafy_api.auth import SESSION_COOKIE, AuthService


session_cookie_scheme = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Opaque host-only browser session cookie.",
)
workspace_pat_scheme = HTTPBearer(
    auto_error=False,
    bearerFormat="PAT",
    description="Workspace-bound personal access token.",
)


def identity_service(request: Request) -> IdentityService:
    return get_identity(request.app).identity_service


IdentityServiceDependency = Annotated[
    IdentityService,
    Depends(identity_service),
]


def auth_service(request: Request) -> AuthService:
    return get_identity(request.app).auth_service


AuthServiceDependency = Annotated[AuthService, Depends(auth_service)]


def identity_uow_factory(
    request: Request,
) -> Callable[[], IdentityUnitOfWorkPort]:
    return get_identity(request.app).identity_uow_factory


IdentityUnitOfWorkFactoryDependency = Annotated[
    Callable[[], IdentityUnitOfWorkPort],
    Depends(identity_uow_factory),
]


async def browser_actor(
    request: Request,
    auth: AuthServiceDependency,
    _session_cookie: Annotated[str | None, Security(session_cookie_scheme)],
) -> ActorContext:
    if "authorization" in request.headers:
        error = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Browser routes accept cookie authentication only",
        )
        await auth.audit_unauthenticated_failure(
            operation="auth.session.verify",
            error_code="authorization_header_rejected",
        )
        request.state.auth_failure_audited = True
        raise error
    try:
        return await auth.require_browser_actor(request)
    except HTTPException as error:
        if error.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            error_code = "rate_limited"
        elif error.detail == "Origin validation failed":
            error_code = "origin_rejected"
        elif error.detail == "CSRF validation failed":
            error_code = "csrf_rejected"
        else:
            error_code = "authentication_required"
        await auth.audit_request_failure(
            request,
            operation="auth.session.verify",
            error_code=error_code,
        )
        request.state.auth_failure_audited = True
        raise


async def workspace_actor(
    workspace_id: UUID,
    request: Request,
    auth: AuthServiceDependency,
    session_cookie: Annotated[str | None, Security(session_cookie_scheme)],
    _bearer: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(workspace_pat_scheme),
    ],
) -> ActorContext | WorkspacePatPrincipal:
    authorization = request.headers.get("authorization")
    if authorization is not None and session_cookie is not None:
        await auth.audit_unauthenticated_failure(
            operation="auth.workspace.verify",
            error_code="ambiguous_credentials",
            workspace_id=workspace_id,
        )
        request.state.auth_failure_audited = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Use either browser session or bearer authentication",
        )
    if authorization is None:
        return await browser_actor(request, auth, session_cookie)
    try:
        principal = await auth.require_workspace_pat_principal(
            request,
            authorization,
        )
    except HTTPException:
        await auth.audit_unauthenticated_failure(
            operation="auth.pat.verify",
            error_code="authentication_required",
            workspace_id=workspace_id,
        )
        request.state.auth_failure_audited = True
        raise
    if principal.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return principal


def require_workspace_capability(capability: WorkspaceCapability):
    async def dependency(
        workspace_id: UUID,
        workspace_principal: Annotated[
            ActorContext | WorkspacePatPrincipal,
            Depends(workspace_actor),
        ],
        identity: IdentityServiceDependency,
    ) -> WorkspaceAccess:
        if isinstance(workspace_principal, WorkspacePatPrincipal):
            workspace_principal.require(capability)
            actor = workspace_principal.actor
        else:
            actor = workspace_principal
        return await identity.authorize(
            actor=actor,
            workspace_id=workspace_id,
            capability=capability,
        )

    return Annotated[WorkspaceAccess, Depends(dependency)]


__all__ = [
    "AuthServiceDependency",
    "IdentityServiceDependency",
    "IdentityUnitOfWorkFactoryDependency",
    "auth_service",
    "browser_actor",
    "identity_service",
    "identity_uow_factory",
    "require_workspace_capability",
    "session_cookie_scheme",
    "workspace_actor",
    "workspace_pat_scheme",
]
