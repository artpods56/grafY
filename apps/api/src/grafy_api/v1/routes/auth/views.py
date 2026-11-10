import logging
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from grafy_core.domain.identity import ActorContext

from grafy_api.v1.routes.auth.dependencies import (
    AuthServiceDependency,
    IdentityUnitOfWorkFactoryDependency,
    browser_actor,
)
from grafy_api.v1.routes.auth.models import SessionResponse
from grafy_api.auth import (
    OIDC_TRANSACTION_COOKIE,
    SESSION_COOKIE,
    OidcCallbackInternalError,
    OidcProtocolError,
    bounded_oidc_failure,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.get("/oidc/login", include_in_schema=True)
async def oidc_login(
    request: Request,
    auth: AuthServiceDependency,
    return_path: Annotated[str, Query(max_length=2048)] = "/",
) -> Response:
    abuse_keys = auth.browser_abuse_keys(request)
    if not await auth.abuse.allow_login_start(
        abuse_keys.browser_key,
        abuse_keys.network_key,
    ):
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.start",
            error_code="rate_limited",
        )
        raise HTTPException(status_code=429, detail="Too many login attempts")
    replaced_transaction_id = await auth.replace_login_transaction(
        request.cookies.get(OIDC_TRANSACTION_COOKIE)
    )
    if replaced_transaction_id is not None:
        await auth.release_login(str(replaced_transaction_id))
    transaction_id = uuid4()
    if not await auth.abuse.reserve_login(
        abuse_keys.browser_key,
        transaction_id,
        abuse_keys.network_key,
    ):
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.start",
            error_code="too_many_login_transactions",
        )
        raise HTTPException(status_code=429, detail="Too many login attempts")
    try:
        authorization_url, transaction_id = await auth.start_login(
            return_path=return_path,
            transaction_id=transaction_id,
        )
    except OidcProtocolError as error:
        await auth.release_login(str(transaction_id))
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.start",
            error_code=error.code,
        )
        raise bounded_oidc_failure(error) from error
    except Exception:
        await auth.release_login(str(transaction_id))
        raise
    response = RedirectResponse(authorization_url, status_code=307)
    auth.set_transaction_cookie(response, str(transaction_id))
    return response


@router.get("/oidc/callback", include_in_schema=True)
async def oidc_callback(
    request: Request,
    auth: AuthServiceDependency,
    state: Annotated[str | None, Query(max_length=512)] = None,
    code: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> Response:
    abuse_keys = auth.browser_abuse_keys(request)
    transaction_id_value = request.cookies.get(OIDC_TRANSACTION_COOKIE)
    if not await auth.abuse.allow_callback(
        abuse_keys.browser_key,
        abuse_keys.network_key,
    ):
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.callback",
            error_code="rate_limited",
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many callback attempts"},
        )
    try:
        _, issued, return_path = await auth.callback(
            transaction_id_value=transaction_id_value,
            state=state,
            code=code,
            error=error,
            current_session_cookie=request.cookies.get(SESSION_COOKIE),
        )
    except OidcProtocolError as protocol_error:
        if protocol_error.transaction_consumed:
            await auth.release_login(transaction_id_value)
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.callback",
            error_code=protocol_error.code,
        )
        failure = bounded_oidc_failure(protocol_error)
        response = JSONResponse(
            status_code=failure.status_code,
            content={"detail": failure.detail},
        )
        auth.clear_transaction_cookie(response)
        return response
    except OidcCallbackInternalError as internal_error:
        if internal_error.transaction_consumed:
            await auth.release_login(transaction_id_value)
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.callback",
            error_code="internal_error",
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": "OIDC callback failed"},
        )
        if internal_error.transaction_consumed:
            auth.clear_transaction_cookie(response)
        return response
    except Exception as exception:
        logger.warning(
            "oidc_callback_failed operation=oidc.login.callback error_class=%s",
            type(exception).__name__,
        )
        await auth.audit_unauthenticated_failure(
            operation="oidc.login.callback",
            error_code="internal_error",
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": "OIDC callback failed"},
        )
        return response
    await auth.release_login(transaction_id_value)
    response = RedirectResponse(return_path, status_code=303)
    auth.set_session_cookies(response, issued)
    auth.clear_transaction_cookie(response)
    return response


@router.get("/session", response_model=SessionResponse)
async def get_session(
    request: Request,
    _actor: Annotated[ActorContext, Depends(browser_actor)],
    auth: AuthServiceDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
) -> SessionResponse:
    session = await auth.current_session(request)
    async with uow_factory() as unit_of_work:
        user = await unit_of_work.identity.get_user(session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        email=user.email,
        display_name=user.display_name,
        created_at=session.created_at,
        last_used_at=session.last_used_at,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
        current=True,
    )


@router.delete("/session", status_code=204)
async def delete_session(
    request: Request,
    _actor: Annotated[ActorContext, Depends(browser_actor)],
    auth: AuthServiceDependency,
) -> Response:
    await auth.logout(request)
    response = Response(status_code=204)
    auth.clear_session_cookies(response)
    return response


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    auth: AuthServiceDependency,
    uow_factory: IdentityUnitOfWorkFactoryDependency,
) -> list[SessionResponse]:
    sessions = await auth.list_sessions(actor=actor)
    current = await auth.current_session(request)
    async with uow_factory() as unit_of_work:
        user = await unit_of_work.identity.get_user(actor.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return [
        SessionResponse(
            id=session.id,
            user_id=session.user_id,
            email=user.email,
            display_name=user.display_name,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
            current=session.id == current.id,
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str,
    request: Request,
    actor: Annotated[ActorContext, Depends(browser_actor)],
    auth: AuthServiceDependency,
) -> Response:
    try:
        parsed_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    session = await auth.revoke_session(
        actor=actor,
        session_id=parsed_session_id,
    )
    response = Response(status_code=204)
    if session.id == (await auth.current_session(request)).id:
        auth.clear_session_cookies(response)
    return response
