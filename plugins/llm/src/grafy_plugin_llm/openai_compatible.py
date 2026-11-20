from ipaddress import ip_address
from typing import Annotated, Protocol, final, override
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from grafy_core.artifacts import JsonObject, NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.prompt_contracts import PromptMessage
from grafy_core.runtime.artifact_values import inline_model_artifact

import grafy_plugin_llm.prompt as _prompt
import grafy_workbench.schema.nodes as _schema_nodes
from grafy_plugin_llm.artifacts import COMPLETION, CompletionPayload
from grafy_plugin_llm.declaration import LLM
from grafy_workbench.schema.values import JsonSchemaText

_ = (_prompt.__name__, _schema_nodes.__name__)  # notes classes before these ports


LLM.register(inline_model_artifact(COMPLETION, CompletionPayload))


class OpenAICompatibleConfig(NodeConfig):
    base_url: StrictStr = Field(
        default="https://api.openai.com/v1",
        min_length=1,
        description="OpenAI-compatible API base URL, including its version path.",
    )
    model: StrictStr = Field(
        default="gpt-4.1-mini",
        min_length=1,
        description="Provider model identifier.",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature passed to the provider.",
    )
    max_completion_tokens: int = Field(
        default=2_048,
        ge=1,
        le=1_000_000,
        description="Maximum number of generated tokens.",
    )
    timeout_ms: int = Field(
        default=120_000,
        ge=1_000,
        le=900_000,
        description="Maximum provider request time in milliseconds.",
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=5,
        description=(
            "Maximum SDK retries after a failed provider request. Keep at zero "
            "when duplicate provider calls are unacceptable."
        ),
    )
    schema_name: StrictStr = Field(
        default="structured_response",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Provider-facing name used when a JSON Schema is connected.",
    )
    strict: bool = Field(
        default=True,
        description="Whether the provider must enforce a connected JSON Schema.",
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


class OpenAICompatibleInput(NodeInput):
    messages: Annotated[
        list[PromptMessage],
        Field(
            min_length=1, title="Instructions", description="Ordered prompt messages."
        ),
    ]
    json_schema: Annotated[
        JsonSchemaText | None,
        Field(
            title="Answer format",
            description="Optional schema for a structured completion.",
        ),
    ] = None


class OpenAICompatibleOutput(NodeOutput):
    completion: Annotated[
        CompletionPayload,
        Field(
            title="Answer", description="Completion content and safe provider metadata."
        ),
    ]


class OpenAICompatibleProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: StrictStr
    structured_value: JsonObject | None = None
    model: StrictStr = Field(min_length=1)
    response_id: StrictStr | None = None
    finish_reason: StrictStr | None = None
    usage: JsonObject = Field(default_factory=dict)


class OpenAICompatibleProvider(Protocol):
    async def complete(
        self,
        messages: list[PromptMessage],
        json_schema: str | None,
        config: OpenAICompatibleConfig,
        api_key: SecretStr,
        /,
        *,
        workspace_id: UUID,
    ) -> OpenAICompatibleProviderResponse: ...


class OpenAICompatibleProviderError(RuntimeError):
    """A provider failure whose message is safe to show to graph users."""


class OpenAICompatibleExecutionError(UserFacingNodeError):
    pass


def build_openai_compatible_node(
    context: PluginRuntimeContext,
) -> "OpenAICompatibleNode":
    from grafy_plugin_llm.openai_compatible_sdk import (
        OpenAICompatibleSdkProvider,
    )

    return OpenAICompatibleNode(
        provider=OpenAICompatibleSdkProvider(
            uow=context.uow,
            storage=context.storage,
        ),
        node_secrets=context.node_secrets,
    )


@LLM.node(
    operator_id="llm.openai_compatible.chat_completion",
    version=1,
    title="Ask a model",
    factory=build_openai_compatible_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            description=(
                "Write-only bearer credential for the configured API base URL."
            ),
            config_dependencies=("base_url",),
        ),
    ),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
    ),
)
@final
class OpenAICompatibleNode(
    Node[
        OpenAICompatibleConfig,
        OpenAICompatibleInput,
        OpenAICompatibleOutput,
    ]
):
    """Sends the instructions to a chat model and keeps the answer."""

    def __init__(
        self,
        *,
        provider: OpenAICompatibleProvider,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._provider = provider
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: OpenAICompatibleConfig,
        inputs: OpenAICompatibleInput,
        /,
    ) -> OpenAICompatibleOutput:
        try:
            api_key = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                graph_id=context.graph_id,
                node_id=context.node_id,
                name="api_key",
                dependencies={"base_url": config.base_url},
            )
        except Exception as exc:
            raise OpenAICompatibleExecutionError(
                "OpenAI-compatible completion could not resolve its API key for "
                f"node {context.node_id!r}, model {config.model!r}, and base URL "
                f"{config.base_url!r}"
            ) from exc

        schema_text = None if inputs.json_schema is None else inputs.json_schema.value
        try:
            response = await self._provider.complete(
                inputs.messages,
                schema_text,
                config,
                api_key,
                workspace_id=context.workspace_id,
            )
            return OpenAICompatibleOutput(
                completion=CompletionPayload(
                    content=response.content,
                    structured_value=response.structured_value,
                    model=response.model,
                    base_url=config.base_url,
                    response_id=response.response_id,
                    finish_reason=response.finish_reason,
                    message_count=len(inputs.messages),
                    source_image_artifact_ids=[
                        ref.artifact_id
                        for message in inputs.messages
                        for ref in message.image_refs
                    ],
                    schema=schema_text,
                    schema_name=(
                        config.schema_name if schema_text is not None else None
                    ),
                    schema_strict=(config.strict if schema_text is not None else None),
                    usage=response.usage,
                )
            )
        except OpenAICompatibleProviderError as exc:
            raise OpenAICompatibleExecutionError(str(exc)) from exc
        except Exception as exc:
            structured_context = (
                f"structured schema {config.schema_name!r}"
                if schema_text is not None
                else "text output"
            )
            raise OpenAICompatibleExecutionError(
                "OpenAI-compatible completion failed for "
                f"{structured_context}, model {config.model!r}, base URL "
                f"{config.base_url!r}, and {len(inputs.messages)} messages"
            ) from exc
