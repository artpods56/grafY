from ipaddress import ip_address
from typing import Annotated, NoReturn

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from grafy_core.artifacts import NodeConfig
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import NodeExecutionContext, UserFacingNodeError
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort

from grafy_plugin_typesafe.limits import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MAX_QUESTION_ID_LENGTH,
    QUESTION_ID_PATTERN,
)


class TypeSafeConnectionConfig(NodeConfig):
    base_url: StrictStr = Field(
        default=DEFAULT_BASE_URL,
        min_length=1,
        description="TypeSafe API root. The SDK appends /v1/systemone.",
    )
    model: StrictStr = Field(
        default=DEFAULT_MODEL,
        min_length=1,
        max_length=256,
        description="Model id or alias, such as jev-latest or jev-1.13.0.",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        description="Per-request HTTP timeout in seconds.",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Retries after the first attempt for rate limits and server errors.",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("base_url must not have surrounding whitespace")
        url = TypeAdapter(AnyHttpUrl).validate_python(value)
        if url.username is not None or url.password is not None:
            raise ValueError("base_url must not include user information")
        if url.query is not None:
            raise ValueError("base_url must not include a query")
        if url.fragment is not None:
            raise ValueError("base_url must not include a fragment")
        host = url.host
        if host is None:
            raise ValueError("base_url must include a host")
        if url.scheme == "http":
            is_loopback = host == "localhost"
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            if not is_loopback:
                try:
                    is_loopback = ip_address(host).is_loopback
                except ValueError:
                    is_loopback = False
            if not is_loopback:
                raise ValueError(
                    "base_url must use HTTPS unless it targets localhost or a "
                    "loopback IP address"
                )
        return str(url).rstrip("/")

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value != value.strip() or any(character.isspace() for character in value):
            raise ValueError("model must not contain whitespace")
        return value


API_CAPABILITIES = (
    PluginRuntimeCapability.NETWORK_EGRESS,
    PluginRuntimeCapability.NODE_SECRETS,
)
API_SECRET = (
    NodeSecretInput(
        name="api_key",
        title="API key",
        description="Write-only TypeSafe API key for the configured base URL.",
        config_dependencies=("base_url",),
    ),
)
API_EGRESS = NodeHttpEgressContract(
    configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
)


async def resolve_api_key(
    *,
    context: NodeExecutionContext,
    config: TypeSafeConnectionConfig,
    node_secrets: NodeSecretResolverPort,
) -> SecretStr:
    try:
        return await node_secrets.resolve_secret(
            workspace_id=context.workspace_id,
            graph_id=context.secret_graph_id,
            graph_revision=context.secret_graph_revision,
            node_id=context.node_id,
            name="api_key",
            dependencies={"base_url": config.base_url},
        )
    except Exception as exc:
        raise UserFacingNodeError(
            "TypeSafe could not resolve its API key for "
            f"node {context.node_id!r} and base URL {config.base_url!r}"
        ) from exc


def shown(exc: ValueError) -> UserFacingNodeError:
    message = str(exc).strip()
    if message == "" or len(message) > 300:
        message = "TypeSafe node input was invalid"
    return UserFacingNodeError(message)


def raise_shown(exc: Exception) -> NoReturn:
    if isinstance(exc, ValidationError):
        message = "TypeSafe node input was invalid"
        errors = exc.errors()
        if errors:
            candidate = errors[0].get("msg", "")
            if candidate.strip() and len(candidate) <= 300:
                message = candidate.removeprefix("Value error, ")
        raise UserFacingNodeError(message) from exc
    if isinstance(exc, ValueError):
        raise shown(exc) from exc
    raise exc


QuestionId = Annotated[
    StrictStr,
    Field(
        min_length=1,
        max_length=MAX_QUESTION_ID_LENGTH,
        pattern=QUESTION_ID_PATTERN.pattern,
    ),
]
