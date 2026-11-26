"""Vision LLM CropTextReader provider node (`llm.crop_reader.provider@1`)."""

from collections.abc import Sequence
from hashlib import sha256
from typing import Annotated, Protocol, final, override
from uuid import UUID

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.config_ui import field_ui
from grafy_core.contracts.ocr import CropTextReader, ServiceCacheIdentity, TextReading
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import Node, NodeExecutionContext, UserFacingNodeError
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from pydantic import Field, SecretStr, StrictStr, field_validator

from grafy_plugin_llm.crop_sheet import SHEET_FORMAT_VERSION
from grafy_plugin_llm.declaration import LLM
from grafy_plugin_llm.ocr import OCR_API_KEY
from grafy_plugin_llm.openai_compatible import validate_openai_base_url

_DEFAULT_SYSTEM_PROMPT = (
    "Transcribe each numbered text crop verbatim. "
    "Preserve original spelling, diacritics, capitalization, and punctuation. "
    "Return an empty string for blank or illegible crops."
)
_DEFAULT_USER_PROMPT = "Read every numbered text crop on this contact sheet."
_MAX_WAVE_BATCH_SIZE = 128


class VisionLlmCropReaderConfig(NodeConfig):
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
        description=(
            "Domain instructions telling the model how to transcribe text crops. "
            "The provider appends the numbered JSON output schema automatically."
        ),
        json_schema_extra=field_ui(widget="textarea"),
    )
    user_prompt: StrictStr = Field(
        default=_DEFAULT_USER_PROMPT,
        title="User instructions",
        description="Instructions sent alongside each contact-sheet image.",
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
        description="Maximum number of generated tokens per contact sheet.",
        json_schema_extra=field_ui(advanced=True),
    )
    max_sheet_crops: int = Field(
        default=16,
        ge=1,
        le=32,
        title="Max crops per sheet",
        description="Maximum number of text crops packed onto one contact-sheet image.",
        json_schema_extra=field_ui(advanced=True),
    )
    max_sheet_edge: int = Field(
        default=1_536,
        ge=512,
        le=2_048,
        title="Max sheet edge (px)",
        description="Maximum width and height in pixels of each contact-sheet image.",
        json_schema_extra=field_ui(advanced=True),
    )
    max_concurrency: int = Field(
        default=4,
        ge=1,
        le=12,
        title="Max concurrent sheets",
        description="Maximum number of contact-sheet requests running at the same time.",
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
            "when duplicate OCR calls are unacceptable."
        ),
        json_schema_extra=field_ui(advanced=True),
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return validate_openai_base_url(value)


class VisionLlmCropReaderError(UserFacingNodeError):
    """A crop-recognition provider failure whose message is safe to show to users."""


class VisionLlmCropReaderProvider(Protocol):
    async def recognize(
        self,
        *,
        crops: Sequence[bytes],
        config: VisionLlmCropReaderConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> list[TextReading]: ...


def _cache_revision(model: str) -> str:
    candidate = f"{SHEET_FORMAT_VERSION}:{model.strip()}"
    if len(candidate) <= 255:
        return candidate
    digest = sha256(model.encode("utf-8")).hexdigest()
    return f"{SHEET_FORMAT_VERSION}:sha256:{digest}"


@final
class VisionLlmCropTextReader(CropTextReader):
    """Packs text crops into numbered contact sheets and reads them with a VLM."""

    def __init__(
        self,
        *,
        config: VisionLlmCropReaderConfig,
        api_key: SecretStr,
        workspace_id: UUID,
        provider: VisionLlmCropReaderProvider,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._provider = provider

    @property
    def preferred_batch_size(self) -> int:
        return max(
            1,
            min(
                self._config.max_sheet_crops * self._config.max_concurrency,
                _MAX_WAVE_BATCH_SIZE,
            ),
        )

    def cache_identity(self) -> ServiceCacheIdentity:
        return ServiceCacheIdentity(
            deployment="llm.crop_reader",
            revision=_cache_revision(self._config.model),
            options={
                "base_url": self._config.base_url,
                "model": self._config.model,
                "system_prompt": self._config.system_prompt,
                "user_prompt": self._config.user_prompt,
                "temperature": self._config.temperature,
                "max_completion_tokens": self._config.max_completion_tokens,
                "max_sheet_crops": self._config.max_sheet_crops,
                "max_sheet_edge": self._config.max_sheet_edge,
            },
        )

    async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
        if not crops:
            return []
        return await self._provider.recognize(
            crops=crops,
            config=self._config,
            api_key=self._api_key,
            workspace_id=self._workspace_id,
        )


class VisionLlmCropReaderInput(NodeInput):
    pass


class VisionLlmCropReaderOutput(NodeOutput):
    recognizer: Annotated[
        VisionLlmCropTextReader,
        Field(
            title="Text recognizer",
            description=(
                "Reads text from cropped image regions using a vision language model."
            ),
        ),
    ]


def build_vision_llm_crop_reader_node(
    context: PluginRuntimeContext,
) -> "VisionLlmCropReaderNode":
    from grafy_plugin_llm.crop_reader_sdk import VisionLlmCropReaderSdkProvider

    return VisionLlmCropReaderNode(
        provider=VisionLlmCropReaderSdkProvider(),
        node_secrets=context.node_secrets,
    )


@LLM.node(
    operator_id="llm.crop_reader.provider",
    version=1,
    title="Vision LLM text recognizer",
    factory=build_vision_llm_crop_reader_node,
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
class VisionLlmCropReaderNode(
    Node[
        VisionLlmCropReaderConfig,
        VisionLlmCropReaderInput,
        VisionLlmCropReaderOutput,
    ]
):
    """Supplies a vision-model text recognizer for cropped regions. Connect it to Read detected TIFF text."""

    def __init__(
        self,
        *,
        provider: VisionLlmCropReaderProvider,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._provider = provider
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: VisionLlmCropReaderConfig,
        _inputs: VisionLlmCropReaderInput,
        /,
    ) -> VisionLlmCropReaderOutput:
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
            raise VisionLlmCropReaderError(
                "Vision LLM text recognizer could not resolve its API key for "
                f"node {context.node_id!r}, model {config.model!r}, and base URL "
                f"{config.base_url!r}"
            ) from exc
        return VisionLlmCropReaderOutput(
            recognizer=VisionLlmCropTextReader(
                config=config,
                api_key=api_key,
                workspace_id=context.workspace_id,
                provider=self._provider,
            )
        )
