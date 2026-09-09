from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar, Literal
import re
import secrets
import warnings
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from grafy_api.plugins.runtime.egress import (
    PluginEgressBrokerPolicy,
    PluginEgressDestination,
    PluginEgressProtocol,
)
from grafy_api.plugins.runtime.network_policy import (
    NetworkPolicy,
    NetworkPolicyError,
    legacy_network_policy,
    load_network_policy_manifest,
)
from grafy_core.domain.identity import (
    OidcDomainWorkspaceGrant,
    parse_oidc_domain_workspace_grants,
)


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

STAGED_UPLOAD_HARD_MAX_BYTES = 64 * 1024 * 1024
_BUILD_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_EPHEMERAL_BUILD_DIGEST: str | None = None


def _ephemeral_build_digest() -> str:
    global _EPHEMERAL_BUILD_DIGEST
    if _EPHEMERAL_BUILD_DIGEST is None:
        _EPHEMERAL_BUILD_DIGEST = secrets.token_hex(32)
    return _EPHEMERAL_BUILD_DIGEST


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GRAFY_",
        extra="ignore",
    )

    workspace: Path = Path(".grafy-artifacts/workbench")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_renderer: Literal["console", "json"] = "console"
    environment: Literal["production", "development"] = "development"
    build_digest: str | None = Field(default=None, pattern=_BUILD_DIGEST_PATTERN)
    public_origin: str = "http://localhost:3000"
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
    # Verified email domains that receive shared Workspace membership on login.
    # Each grant is `domain:slug` or `domain:slug:name`.
    oidc_domain_workspaces: Annotated[
        tuple[OidcDomainWorkspaceGrant, ...],
        NoDecode,
    ] = ()
    auth_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    auth_login_start_rate_limit: int = Field(default=10, ge=1)
    auth_callback_rate_limit: int = Field(default=20, ge=1)
    auth_session_failure_rate_limit: int = Field(default=30, ge=1)
    auth_pat_creation_rate_limit: int = Field(default=10, ge=1)
    auth_outstanding_login_limit: int = Field(default=2, ge=1, le=10)
    auth_outstanding_login_network_limit: int = Field(default=8, ge=1, le=40)
    auth_cleanup_interval_seconds: int = Field(default=60, ge=1, le=3600)
    database_url: SecretStr | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    map_max_concurrency: int = Field(default=4, ge=1)
    max_active_executions: int = Field(default=2, ge=1, le=32)
    max_pending_graphs: int = Field(default=20, ge=1, le=1_000)
    max_active_plugin_invocations: int = Field(default=4, ge=1, le=128)
    plugin_invocation_wall_time_seconds_by_slug: dict[str, int] = Field(
        default_factory=dict,
    )
    max_live_plugin_sandboxes: int = Field(default=4, ge=1, le=64)
    max_distinct_plugin_releases_per_graph: int = Field(default=4, ge=1, le=64)
    # Origin-keyed sandboxes turn one release into multiple variants. This
    # bound must never exceed global live-sandbox capacity.
    max_plugin_sandbox_variants_per_execution: int = Field(default=4, ge=1, le=64)
    storage_backend: Literal["local", "s3"] = "local"
    plugin_roots: tuple[Path, ...] = (
        Path("examples"),
        Path("plugins"),
        Path(".grafy-artifacts/workspace-plugins"),
    )
    # Coding-agent authoring is assigned deterministically beneath this
    # deployment-owned Plugin root. It never chooses an arbitrary host path.
    plugin_authoring_root: Path = Path(".grafy-artifacts/workspace-plugins")
    # Source used to build the versioned SDK wheel vendored into a generated
    # working copy. The resulting Plugin has no monorepo-relative dependency.
    plugin_sdk_project: Path = Path("libs/core")
    # Deployment-owned default runtime profile for published Plugin releases.
    plugin_runtime_profile: Literal[
        "python-uv",
        "python-uv-gdal",
        "python-uv-tesseract",
        "python-uv-gdal-tesseract",
    ] = "python-uv"
    plugin_runtime_native_base_image: str | None = None
    plugin_runtime_native_base_image_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    # Exact System Plugin host bindings are loaded once at API startup from this
    # deployment manifest. When omitted, startup registers Module boundaries only.
    system_plugin_deployment_manifest: Path | None = None
    # Workspace Plugin execution is fail-closed unless the local Docker
    # sandbox owner is explicitly enabled for this single API process.
    plugin_runtime_enabled: bool = False
    plugin_docker_binary: str = Field(default="docker", min_length=1, max_length=1_024)
    # The Docker daemon must be able to bind this host path into one-shot
    # publisher containers. The local default stays beneath the repository.
    plugin_publisher_scratch_root: Path = Path(".grafy-artifacts/plugin-publisher")
    plugin_runtime_seccomp_profile: Path | None = None
    plugin_egress_broker_image: str | None = None
    # Legacy translation inputs. When GRAFY_NETWORK_POLICY_MANIFEST is set it
    # owns plugin-execution HTTP authority and these values are ignored for
    # that plane (they remain the source for postgresql.egress only).
    plugin_http_egress_destinations: tuple[str, ...] = ()
    plugin_postgresql_egress_destinations: tuple[str, ...] = ()
    # Versioned deployment manifest of network access profiles and their
    # assignments. When configured, it replaces legacy HTTP destination grants
    # for Plugin execution; its absence translates the legacy egress variables.
    network_policy_manifest: Path | None = None
    # Deployment-owned directory of versioned Grafy Plugin SDK wheels (e.g. a
    # built grapy-core wheel) exposed to Plugin dependency resolution via
    # UV_FIND_LINKS. Plugins never depend on monorepo paths.
    plugin_wheelhouse: Path | None = None
    storage_bucket: str = Field(default="workbench-artifacts", min_length=1)
    staged_upload_max_bytes: int = Field(
        default=STAGED_UPLOAD_HARD_MAX_BYTES,
        ge=1024 * 1024,
        le=STAGED_UPLOAD_HARD_MAX_BYTES,
    )
    s3_endpoint_url: str | None = None
    s3_region: str = Field(default="us-east-1", min_length=1)
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = False
    credential_encryption_key: SecretStr | None = None
    command_hmac_key: SecretStr | None = None
    command_hmac_key_version: int = Field(default=1, ge=1)
    # Application graph-room heartbeat interval. Zero disables heartbeats
    # (useful for focused unit tests). Production default revalidates membership
    # when post-commit room invalidation is lost.
    graph_room_heartbeat_seconds: float = Field(default=15.0, ge=0.0, le=120.0)
    # Ephemeral presence: clear cursor/activity after TTL; remove idle entries at 2×.
    graph_room_presence_ttl_seconds: float = Field(default=5.0, ge=0.5, le=120.0)
    # Best-effort cursor budget (~20 Hz). Excess updates are dropped, not rejected.
    graph_room_presence_max_updates_per_second: float = Field(
        default=20.0,
        ge=1.0,
        le=60.0,
    )
    # Collaboration and shared execution assume one FastAPI process with one
    # HTTP worker. Startup acquires an exclusive lock under workspace when true.
    require_single_api_owner: bool = True

    @model_validator(mode="after")
    def validate_plugin_capacity(self) -> "Settings":
        if self.max_distinct_plugin_releases_per_graph > self.max_live_plugin_sandboxes:
            raise ValueError(
                "max_distinct_plugin_releases_per_graph cannot exceed "
                "max_live_plugin_sandboxes"
            )
        if (
            self.max_plugin_sandbox_variants_per_execution
            > self.max_live_plugin_sandboxes
        ):
            raise ValueError(
                "max_plugin_sandbox_variants_per_execution cannot exceed "
                "max_live_plugin_sandboxes"
            )
        return self

    @field_validator("plugin_invocation_wall_time_seconds_by_slug")
    @classmethod
    def validate_plugin_invocation_wall_times(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        for slug, seconds in value.items():
            if re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*", slug) is None:
                raise ValueError(f"Invalid Plugin slug {slug!r}")
            if seconds < 1 or seconds > 3_600:
                raise ValueError(
                    f"Plugin invocation wall time for {slug!r} must be between "
                    "1 and 3600 seconds"
                )
        return value

    @model_validator(mode="after")
    def validate_plugin_egress(self) -> "Settings":
        destinations = (
            *self.plugin_http_egress_destinations,
            *self.plugin_postgresql_egress_destinations,
        )
        if self.network_policy_manifest is None and (
            bool(self.plugin_egress_broker_image) != bool(destinations)
        ):
            raise ValueError(
                "plugin_egress_broker_image and at least one exact egress "
                "destination must be configured together"
            )
        parsed_http = tuple(
            PluginEgressDestination.parse(value)
            for value in self.plugin_http_egress_destinations
        )
        if any(
            destination.protocol is PluginEgressProtocol.POSTGRESQL
            for destination in parsed_http
        ):
            raise ValueError(
                "plugin_http_egress_destinations accepts only HTTP or HTTPS"
            )
        parsed_postgresql = tuple(
            PluginEgressDestination.parse(value)
            for value in self.plugin_postgresql_egress_destinations
        )
        if any(
            destination.protocol is not PluginEgressProtocol.POSTGRESQL
            for destination in parsed_postgresql
        ):
            raise ValueError(
                "plugin_postgresql_egress_destinations accepts only PostgreSQL"
            )
        PluginEgressBrokerPolicy(
            broker_image=self.plugin_egress_broker_image,
            destinations=(*parsed_http, *parsed_postgresql),
        )
        return self

    @field_validator("oidc_domain_workspaces", mode="before")
    @classmethod
    def _parse_oidc_domain_workspaces(cls, value: object) -> object:
        if value is None or value == "":
            return ()
        if isinstance(value, str | list | tuple):
            return parse_oidc_domain_workspace_grants(value)
        return value

    @field_validator("plugin_egress_broker_image", mode="before")
    @classmethod
    def empty_plugin_egress_broker_image_is_unset(
        cls,
        value: object,
    ) -> object:
        return None if value == "" else value

    @field_validator("public_origin", "oidc_issuer")
    @classmethod
    def _validate_origin_or_issuer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OIDC origin and issuer must be absolute HTTP URLs")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "OIDC origin and issuer must not contain query or fragment"
            )
        return value.rstrip("/")

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
    def _validate_oidc_configuration(self) -> "Settings":
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

    @property
    def resolved_build_digest(self) -> str:
        if self.build_digest is not None:
            return self.build_digest
        if self.environment == "production":
            raise ValueError("GRAFY_BUILD_DIGEST is required in production")
        return _ephemeral_build_digest()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        database_path = (self.workspace / "grafy.sqlite3").resolve()
        return f"sqlite+aiosqlite:///{database_path}"

    @property
    def allowed_cors_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        )

    @property
    def resolved_plugin_roots(self) -> tuple[Path, ...]:
        return tuple(root.expanduser().resolve() for root in self.plugin_roots)

    @property
    def resolved_plugin_wheelhouse(self) -> Path | None:
        if self.plugin_wheelhouse is None:
            return None
        return self.plugin_wheelhouse.expanduser().resolve()

    @property
    def resolved_plugin_authoring_root(self) -> Path:
        return self.plugin_authoring_root.expanduser().resolve()

    @property
    def resolved_plugin_publisher_scratch_root(self) -> Path:
        return self.plugin_publisher_scratch_root.expanduser().resolve()

    @property
    def resolved_plugin_sdk_project(self) -> Path:
        return self.plugin_sdk_project.expanduser().resolve()

    @property
    def resolved_system_plugin_deployment_manifest(self) -> Path | None:
        if self.system_plugin_deployment_manifest is None:
            return None
        return self.system_plugin_deployment_manifest.expanduser().resolve()

    @property
    def resolved_network_policy_manifest(self) -> Path | None:
        if self.network_policy_manifest is None:
            return None
        return self.network_policy_manifest.expanduser().resolve()

    @property
    def resolved_network_policy(self) -> NetworkPolicy:
        """The deployment-owned network policy, manifest-first.

        Without a manifest the legacy egress environment variables translate
        into an in-memory curated execution profile so historical
        ``network.egress`` releases keep their exact previous authority.
        """

        manifest = self.resolved_network_policy_manifest
        if manifest is not None:
            try:
                return load_network_policy_manifest(manifest)
            except NetworkPolicyError as exc:
                raise NetworkPolicyError(
                    f"GRAFY_NETWORK_POLICY_MANIFEST {manifest} is invalid: {exc}"
                ) from exc
        legacy_destinations = tuple(
            PluginEgressDestination.parse(value)
            for value in self.plugin_http_egress_destinations
        )
        if legacy_destinations:
            warnings.warn(
                "GRAFY_PLUGIN_HTTP_EGRESS_DESTINATIONS is deprecated and "
                "translates into the legacy-curated execution profile; set "
                "GRAFY_NETWORK_POLICY_MANIFEST to assign named network access "
                "profiles.",
                category=DeprecationWarning,
                stacklevel=2,
            )
        return legacy_network_policy(http_destinations=legacy_destinations)

    @property
    def resolved_plugin_seccomp_profile(self) -> Path | None:
        if self.plugin_runtime_seccomp_profile is None:
            return None
        return self.plugin_runtime_seccomp_profile.expanduser().resolve()

    @property
    def resolved_plugin_egress_policy(self) -> PluginEgressBrokerPolicy:
        """Broker infrastructure policy for the isolated runtime.

        With a network policy manifest, plugin-execution HTTP authority comes
        from the manifest and legacy HTTP destinations are excluded here;
        PostgreSQL keeps its separate destination-scoped allowlist either way.
        """

        legacy_http = (
            ()
            if self.network_policy_manifest is not None
            else (
                PluginEgressDestination.parse(value)
                for value in self.plugin_http_egress_destinations
            )
        )
        return PluginEgressBrokerPolicy(
            broker_image=self.plugin_egress_broker_image,
            destinations=tuple(
                [
                    *legacy_http,
                    *(
                        PluginEgressDestination.parse(value)
                        for value in self.plugin_postgresql_egress_destinations
                    ),
                ]
            ),
        )

    @property
    def oidc_callback_url(self) -> str:
        return f"{self.public_origin}{self.oidc_callback_path}"

    @property
    def oidc_is_configured(self) -> bool:
        return self.oidc_issuer is not None

    def resolved_command_hmac_key(self) -> bytes:
        """Return the deployment HMAC key, failing closed when unset or empty."""
        configured = self.command_hmac_key
        if configured is None:
            raise ValueError(
                "GRAFY_COMMAND_HMAC_KEY must be configured for collaboration"
            )
        value = configured.get_secret_value()
        if value == "":
            raise ValueError("GRAFY_COMMAND_HMAC_KEY must not be empty")
        return value.encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
