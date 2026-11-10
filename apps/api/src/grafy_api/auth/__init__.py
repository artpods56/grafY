"""Application authentication: OIDC, sessions, tokens, and abuse control."""

from grafy_api.auth.errors import OidcCallbackInternalError, OidcProtocolError
from grafy_api.auth.http import (
    CSRF_COOKIE,
    OIDC_TRANSACTION_COOKIE,
    SESSION_COOKIE,
    bounded_oidc_failure,
)
from grafy_api.auth.provider import ProviderMetadata
from grafy_api.auth.secrets import digest_secret
from grafy_api.auth.service import AuthService
from grafy_api.auth.sessions import IssuedSession

__all__ = [
    "AuthService",
    "CSRF_COOKIE",
    "IssuedSession",
    "OIDC_TRANSACTION_COOKIE",
    "OidcCallbackInternalError",
    "OidcProtocolError",
    "ProviderMetadata",
    "SESSION_COOKIE",
    "bounded_oidc_failure",
    "digest_secret",
]
