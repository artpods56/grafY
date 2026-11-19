"""Detect text in a selected area or page of a TIFF and place it on the source page."""

from typing import Literal, cast, final, override

from pydantic import BaseModel, ConfigDict, Field

from grafy_core.artifacts import (
    ArtifactReferenceContract,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.documents import TiffFile
from grafy_core.file_contracts import TIFF_FILE
from grafy_core.node_context import UserFacingNodeError
from grafy_core.node_ports import Ref
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.provider_cache import ProviderCache
from grafy_core.runtime.artifact_values import inline_model_artifact
from grafy_core.text_regions import TextDetector, TextRegion, TiffPageOpener

from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.tiff_scan import Window, detect_area


class TiffPixelWindow(BaseModel):
    page: int = Field(default=0, ge=0, title="TIFF page (zero-based)")
    col: int = Field(default=0, ge=0, title="Left pixel")
    row: int = Field(default=0, ge=0, title="Top pixel")
    width: int = Field(default=512, gt=0, title="Width in pixels")
    height: int = Field(default=512, gt=0, title="Height in pixels")


class DetectTextConfig(TiffPixelWindow, NodeConfig):
    scope: Literal["Selected area", "Whole TIFF page"] = Field(
        default="Selected area", title="Scan area"
    )
    strategy: Literal["Automatic", "Single crop"] = Field(
        default="Automatic", title="Window strategy"
    )


class TiffTextRegions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Ref[TiffFile]
    window: TiffPixelWindow
    regions: list[TextRegion]


OCR.register_service_contract(TextDetector)
OCR.register_artifact_type_dependency(TIFF_FILE)
OCR.register(
    inline_model_artifact(
        ArtifactTypeSpec(
            key=ArtifactTypeKey("ocr.tiff_text_regions", 1),
            title="TIFF text regions",
            payload_schema=cast(JsonObject, TiffTextRegions.model_json_schema()),
            references=(
                ArtifactReferenceContract(
                    path=("source",), target=TIFF_FILE.key, shape="one"
                ),
            ),
        ),
        TiffTextRegions,
    )
)


class DetectTextInput(NodeInput):
    tiff: Ref[TiffFile] = Field(title="TIFF")
    detector: TextDetector = Field(title="Detector")


class DetectTextOutput(NodeOutput):
    regions: TiffTextRegions = Field(title="Text regions")


@OCR.node(
    operator_id="ocr.detect_tiff_text",
    version=1,
    title="Detect text in TIFF window",
    factory=lambda context: DetectTiffTextNode(
        context.open_tiff_page,
        cache=context.provider_cache,
        cache_ttl_seconds=context.provider_cache_ttl_seconds,
    ),
)
@final
class DetectTiffTextNode(Node[DetectTextConfig, DetectTextInput, DetectTextOutput]):
    def __init__(
        self,
        open_page: TiffPageOpener | None,
        *,
        cache: ProviderCache | None = None,
        cache_ttl_seconds: int = 30 * 24 * 60 * 60,
    ) -> None:
        self._open_page = open_page
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: DetectTextConfig,
        inputs: DetectTextInput,
        /,
    ) -> DetectTextOutput:
        if self._open_page is None:
            raise UserFacingNodeError("TIFF window reading is unavailable")
        page = await self._open_page(
            context.workspace_id, inputs.tiff.artifact_id, page=config.page
        )
        area = (
            Window(0, 0, page.width, page.height)
            if config.scope == "Whole TIFF page"
            else Window(config.col, config.row, config.width, config.height)
        )
        regions = await detect_area(
            context,
            page,
            inputs.detector,
            area,
            single=config.strategy == "Single crop",
            cache=self._cache,
            cache_ttl_seconds=self._cache_ttl_seconds,
        )
        return DetectTextOutput(
            regions=TiffTextRegions(
                source=inputs.tiff,
                window=TiffPixelWindow(
                    page=config.page,
                    col=area.col,
                    row=area.row,
                    width=area.width,
                    height=area.height,
                ),
                regions=regions,
            )
        )
