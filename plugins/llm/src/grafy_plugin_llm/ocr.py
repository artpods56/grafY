from typing import Annotated, ClassVar, Protocol, final, override
from uuid import UUID

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import field_ui
from grafy_core.contracts.ocr import DocumentOcr, DocumentOcrFeature, DocumentOcrResult
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import Node, NodeExecutionContext, UserFacingNodeError
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from pydantic import Field, SecretStr, StrictStr, field_validator

from grafy_plugin_llm.declaration import LLM
from grafy_plugin_llm.openai_compatible import (
    validate_openai_base_url,
    verify_openai_compatible_api_key,
)

_DEFAULT_SYSTEM_PROMPT = (
    "Transcribe the document accurately into clean Markdown. "
    "Preserve headings, lists, tables, and reading order. "
    "Do not add commentary."
)


class VisionLlmOcrConfig(NodeConfig):
    base_url: StrictStr = Field(
        default="https://api.openai.com/v1",
        min_length=1,
        title="Base URL",
        description="OpenAI-compatible API base URL, including its version path.",
        json_schema_extra=field_ui(advanced=True),
    )
    model: StrictStr = Field(
        default="gpt-4.1-mini",
        min_length=1,
        title="Model",
        description="Vision model identifier.",
    )
    system_prompt: StrictStr = Field(
        default=_DEFAULT_SYSTEM_PROMPT,
        title="System instructions",
        description="Instructions that tell the model how to transcribe the page.",
        json_schema_extra=field_ui(widget="textarea"),
    )
    user_prompt: StrictStr = Field(
        default="Transcribe this document page into clean Markdown.",
        title="User instructions",
        description="Instructions sent with the page image.",
        json_schema_extra=field_ui(widget="textarea"),
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        title="Temperature",
        description="Sampling temperature passed to the provider.",
        json_schema_extra=field_ui(advanced=True, widget="slider"),
    )
    max_completion_tokens: int = Field(
        default=4_096,
        ge=1,
        le=1_000_000,
        title="Max completion tokens",
        description="Maximum number of generated tokens.",
        json_schema_extra=field_ui(advanced=True),
    )
    timeout_ms: int = Field(
        default=120_000,
        ge=1_000,
        le=900_000,
        title="Time limit (ms)",
        description="Maximum provider request time in milliseconds.",
        json_schema_extra=field_ui(advanced=True),
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=5,
        title="Max retries",
        description=(
            "Maximum SDK retries after a failed provider request. Keep at zero "
            "when a duplicate OCR call is unacceptable."
        ),
        json_schema_extra=field_ui(advanced=True),
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_openai_base_url(value)


class VisionLlmOcrProvider(Protocol):
    async def process(
        self,
        *,
        document: RasterImage | PdfFile,
        config: VisionLlmOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> DocumentOcrResult: ...


class VisionLlmOcrProviderError(UserFacingNodeError):
    """A provider failure whose message is safe to show to graph users."""


class VisionLlmOcrReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset()

    def __init__(
        self,
        *,
        config: VisionLlmOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
        provider: VisionLlmOcrProvider,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._provider = provider

    async def read(self, document: RasterImage | PdfFile) -> DocumentOcrResult:
        return await self._provider.process(
            document=document,
            config=self._config,
            api_key=self._api_key,
            workspace_id=self._workspace_id,
        )


class VisionLlmOcrProviderInput(NodeInput):
    pass


class VisionLlmOcrProviderOutput(NodeOutput):
    engine: Annotated[
        VisionLlmOcrReader,
        Field(
            title="Document OCR engine",
            description=(
                "Reads a scanned image into Markdown with a vision language model."
            ),
        ),
    ]


#: The credential this node reads with `context.secrets.require(OCR_API_KEY.name)`.
OCR_API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    description="Write-only bearer credential for the configured API base URL.",
    config_dependencies=("base_url",),
    provider_kind="openai_compatible",
    verifier=verify_openai_compatible_api_key,
)


def build_vision_llm_ocr_provider_node(
    context: PluginRuntimeContext,
) -> "VisionLlmOcrProviderNode":
    from grafy_plugin_llm.ocr_sdk import VisionLlmOcrSdkProvider

    return VisionLlmOcrProviderNode(
        provider=VisionLlmOcrSdkProvider(),
        node_secrets=context.node_secrets,
    )


@LLM.node(
    operator_id="llm.ocr.provider",
    version=1,
    title="Vision LLM OCR",
    factory=build_vision_llm_ocr_provider_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(OCR_API_KEY,),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
    ),
)
@final
class VisionLlmOcrProviderNode(
    Node[VisionLlmOcrConfig, VisionLlmOcrProviderInput, VisionLlmOcrProviderOutput]
):
    """Supplies a vision-model OCR reader. Connect it to a Document OCR node."""

    def __init__(
        self,
        *,
        provider: VisionLlmOcrProvider,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._provider = provider
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: VisionLlmOcrConfig,
        _inputs: VisionLlmOcrProviderInput,
        /,
    ) -> VisionLlmOcrProviderOutput:
        try:
            if context.secrets.workspace_id is not None:
                api_key = await context.secrets.require(OCR_API_KEY.name)
            else:
                api_key = await self._node_secrets.resolve_secret(
                    workspace_id=context.workspace_id,
                    project_id=context.project_id,
                    graph_id=context.graph_id,
                    node_id=context.node_id,
                    name=OCR_API_KEY.name,
                    dependencies={"base_url": config.base_url},
                    actor_user_id=context.actor_user_id,
                )
        except Exception as exc:
            raise VisionLlmOcrProviderError(
                "Vision LLM OCR could not resolve its API key for "
                f"node {context.node_id!r}, model {config.model!r}, and base URL "
                f"{config.base_url!r}"
            ) from exc
        return VisionLlmOcrProviderOutput(
            engine=VisionLlmOcrReader(
                config=config,
                api_key=api_key,
                workspace_id=context.workspace_id,
                provider=self._provider,
            )
        )
