"""Authentication, session and OIDC configuration."""

from typing import Annotated, ClassVar

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS
from grafy_shared.config.origins import absolute_http_url

_OIDC_ALLOWED_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "PS256",
        "PS384",
        "PS512",
        "ES256",
        "ES384",
        "ES512",
    }
)


class AuthConfig(BaseSettings):
    """Who may sign in, how long they stay, and how often they may try."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_allowed_signing_algorithms: tuple[str, ...] = ("RS256",)
    oidc_auth_wrapping_key: SecretStr | None = None
    oidc_auth_wrapping_key_version: int = Field(default=1, ge=1)
    oidc_login_transaction_ttl_seconds: int = Field(default=300, ge=30, le=900)
    auth_session_idle_seconds: int = Field(default=1800, ge=60)
    auth_session_absolute_seconds: int = Field(default=28800, ge=300)
    personal_access_token_max_lifetime_seconds: int = Field(
        default=2592000,
        ge=60,
    )
    auth_cookie_secure: bool = True
    oidc_callback_path: str = "/api/v1/auth/oidc/callback"
    # Issuer-asserted email domains that receive shared Workspace membership on
    # login. Each grant is `domain:slug` or `domain:slug:name`. grafy-shared is a
    # leaf package, so the grants stay raw strings here and the API parses them
    # with grafy_core.domain.identity.parse_oidc_domain_workspace_grants.
    oidc_domain_workspaces: Annotated[tuple[str, ...], NoDecode] = ()
    auth_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    auth_login_start_rate_limit: int = Field(default=10, ge=1)
    auth_callback_rate_limit: int = Field(default=20, ge=1)
    auth_session_failure_rate_limit: int = Field(default=30, ge=1)
    auth_pat_creation_rate_limit: int = Field(default=10, ge=1)
    auth_outstanding_login_limit: int = Field(default=2, ge=1, le=10)
    auth_outstanding_login_network_limit: int = Field(default=8, ge=1, le=40)
    auth_cleanup_interval_seconds: int = Field(default=60, ge=1, le=3600)

    @field_validator("oidc_domain_workspaces", mode="before")
    @classmethod
    def _parse_oidc_domain_workspaces(cls, value: object) -> object:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("oidc_issuer")
    @classmethod
    def _validate_oidc_issuer(cls, value: str | None) -> str | None:
        return None if value is None else absolute_http_url(value)

    @field_validator("oidc_callback_path")
    @classmethod
    def _validate_callback_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("OIDC callback path must be absolute and relative")
        if "?" in value or "#" in value:
            raise ValueError("OIDC callback path must not contain a query or fragment")
        if value != "/api/v1/auth/oidc/callback":
            raise ValueError("OIDC callback path must be the registered callback")
        return value

    @model_validator(mode="after")
    def _validate_oidc_configuration(self) -> "AuthConfig":
        if self.oidc_client_id is not None and self.oidc_client_id.strip() == "":
            raise ValueError("oidc_client_id must not be empty")
        if (
            self.oidc_auth_wrapping_key is not None
            and self.oidc_auth_wrapping_key.get_secret_value() == ""
        ):
            raise ValueError("oidc_auth_wrapping_key must not be empty")
        if (
            self.oidc_client_secret is not None
            and self.oidc_client_secret.get_secret_value() == ""
        ):
            raise ValueError("oidc_client_secret must be omitted rather than empty")
        configured = (
            self.oidc_issuer,
            self.oidc_client_id,
            self.oidc_auth_wrapping_key,
        )
        if any(value is not None for value in configured) and not all(
            value is not None for value in configured
        ):
            raise ValueError(
                "oidc_issuer, oidc_client_id, and oidc_auth_wrapping_key must be "
                "configured together"
            )
        if not self.oidc_allowed_signing_algorithms:
            raise ValueError("At least one OIDC signing algorithm is required")
        if any(
            algorithm.strip() == "" or algorithm != algorithm.strip()
            for algorithm in self.oidc_allowed_signing_algorithms
        ):
            raise ValueError("OIDC signing algorithms must be non-empty values")
        if any(
            algorithm not in _OIDC_ALLOWED_ALGORITHMS
            for algorithm in self.oidc_allowed_signing_algorithms
        ):
            raise ValueError("OIDC signing algorithm is not allowed")
        if self.auth_session_idle_seconds >= self.auth_session_absolute_seconds:
            raise ValueError(
                "Auth session idle lifetime must be below absolute lifetime"
            )
        return self

    def resolved_callback_url(self, public_origin: str) -> str:
        """The browser-facing OIDC redirect target for this deployment."""

        return f"{public_origin}{self.oidc_callback_path}"

    @property
    def oidc_is_configured(self) -> bool:
        return self.oidc_issuer is not None
