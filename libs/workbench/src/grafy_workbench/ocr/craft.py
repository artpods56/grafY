"""CRAFT text localization through the deployment's scoped LiteLLM route."""

from base64 import b64encode
from typing import final, override

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeSecretInput,
    PluginRuntimeCapability,
)
from grafy_core.text_regions import PixelPolygon, TextDetector, TextRegion

from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.provider_http import ProviderRequest, post_json

CRAFT_URL = "https://ai-test.ihpan.edu.pl/v1/ocr/craft/detect"
CRAFT_MODEL = "craft-mlt-25k@sha256:4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17"
_MAX_RESPONSE_BYTES = 4 * 1024**2


class CraftResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    model: str
    polygons: list[PixelPolygon]


@final
class CraftDetector(TextDetector):
    def __init__(
        self,
        api_key: SecretStr,
        *,
        timeout_ms: int,
        max_retries: int,
        text_threshold: float,
        link_threshold: float,
        low_text: float,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_ms / 1_000
        self._attempts = max_retries + 1
        self.request_options = {
            "text_threshold": text_threshold,
            "link_threshold": link_threshold,
            "low_text": low_text,
        }

    async def detect(self, png: bytes, *, width: int, height: int) -> list[TextRegion]:
        if (
            len(png) > 4 * 1024**2
            or max(width, height) > 4096
            or width * height > 2048**2
        ):
            raise UserFacingNodeError("The TIFF window exceeds CRAFT's image limits")
        body = await post_json(
            ProviderRequest(
                service="CRAFT",
                url=CRAFT_URL,
                payload={
                    "image_base64": b64encode(png).decode("ascii"),
                    **self.request_options,
                },
                api_key=self._api_key,
                attempts=self._attempts,
                timeout_seconds=self._timeout_seconds,
                max_response_bytes=_MAX_RESPONSE_BYTES,
            )
        )
        try:
            result = CraftResponse.model_validate_json(body)
        except ValidationError as exc:
            raise UserFacingNodeError("CRAFT returned invalid text regions") from exc
        if (result.width, result.height) != (width, height):
            raise UserFacingNodeError("CRAFT returned different image dimensions")
        if result.model != CRAFT_MODEL:
            raise UserFacingNodeError("CRAFT returned an unexpected model revision")
        return [TextRegion(polygon=polygon) for polygon in result.polygons]


class CraftInput(NodeInput):
    pass


class CraftConfig(NodeConfig):
    timeout_ms: int = Field(
        title="Time limit (ms)",
        json_schema_extra={"x-grafy-advanced": True},
        default=120_000,
        ge=1_000,
        le=900_000,
        description=(
            "Maximum CRAFT request time in milliseconds. A page scan shares the "
            "provider, so a window waits for the windows ahead of it."
        ),
    )
    max_retries: int = Field(
        title="Max retries",
        json_schema_extra={"x-grafy-advanced": True},
        default=2,
        ge=0,
        le=5,
        description=(
            "Additional attempts after a timeout, connection failure, or retryable "
            "HTTP status. Localizing a window twice returns the same polygons, so a "
            "retry costs provider time and changes nothing else."
        ),
    )
    text_threshold: float = Field(
        title="Text threshold",
        json_schema_extra={"x-grafy-advanced": True},
        default=0.7,
        gt=0,
        le=1,
        description=(
            "Drop any detected region whose peak text score is below this. "
            "Symbol-dense scans (forest glyphs on old maps) produce weak regions; "
            "raising this toward 0.85 removes most of them."
        ),
    )
    link_threshold: float = Field(
        title="Link threshold",
        json_schema_extra={"x-grafy-advanced": True},
        default=0.4,
        gt=0,
        le=1,
        description=(
            "Affinity score a pixel needs to join two character regions into one."
        ),
    )
    low_text: float = Field(
        title="Low text threshold",
        json_schema_extra={"x-grafy-advanced": True},
        default=0.4,
        gt=0,
        le=1,
        description="Text-score floor used while grouping pixels into regions.",
    )


class CraftOutput(NodeOutput):
    detector: CraftDetector = Field(title="Text detector")


@OCR.node(
    operator_id="ocr.craft_provider",
    version=1,
    title="CRAFT text detector",
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    http_egress=NodeHttpEgressContract(
        fixed_destinations=("https://ai-test.ihpan.edu.pl",)
    ),
    secret_inputs=(NodeSecretInput(name="api_key", title="LiteLLM API key"),),
)
@final
class CraftProviderNode(Node[CraftConfig, CraftInput, CraftOutput]):
    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: CraftConfig,
        _inputs: CraftInput,
        /,
    ) -> CraftOutput:
        return CraftOutput(
            detector=CraftDetector(
                await context.secrets.require("api_key"),
                timeout_ms=config.timeout_ms,
                max_retries=config.max_retries,
                text_threshold=config.text_threshold,
                link_threshold=config.link_threshold,
                low_text=config.low_text,
            )
        )
