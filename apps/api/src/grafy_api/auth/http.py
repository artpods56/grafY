"""Cookie and CSRF translation at the browser edge."""

import hmac
from typing import cast

from fastapi import HTTPException, Request, Response, status

from grafy_core.domain.identity import AuthSession

from grafy_api.auth.errors import OidcProtocolError
from grafy_api.auth.secrets import digest_secret
from grafy_api.auth.sessions import IssuedSession


SESSION_COOKIE = "grafy_session"
CSRF_COOKIE = "grafy_csrf"
OIDC_TRANSACTION_COOKIE = "grafy_oidc_transaction"


def set_session_cookies(
    response: Response,
    issued: IssuedSession,
    *,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        issued.cookie_value,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_value,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def clear_transaction_cookie(response: Response) -> None:
    response.delete_cookie(OIDC_TRANSACTION_COOKIE, path="/api/v1/auth/oidc")


def set_transaction_cookie(
    response: Response,
    transaction_id: str,
    *,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        OIDC_TRANSACTION_COOKIE,
        transaction_id,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth/oidc",
    )


def check_cookie_request(request: Request, *, public_origin: str) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("origin") != public_origin:
        raise HTTPException(status_code=403, detail="Origin validation failed")
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf_header = request.headers.get("x-csrf-token")
    if csrf_cookie is None or csrf_header is None:
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    session = cast(AuthSession, request.state.auth_session)
    if not hmac.compare_digest(csrf_cookie, csrf_header) or not hmac.compare_digest(
        session.csrf_digest,
        digest_secret(csrf_header),
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def bounded_oidc_failure(_error: OidcProtocolError) -> HTTPException:
    """The callback's public body stays generic; callers audit ``_error.code``."""

    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="OIDC callback failed",
    )
