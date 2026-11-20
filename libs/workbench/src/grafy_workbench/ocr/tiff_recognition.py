"""Read the text of already localized TIFF regions."""

import asyncio
import hashlib
from collections.abc import Sequence
from itertools import batched
from typing import cast, final, override

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from grafy_core.artifacts import (
    ArtifactReferenceContract,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NoConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.documents import TiffFile
from grafy_core.file_contracts import TIFF_FILE
from grafy_core.node_context import UserFacingNodeError
from grafy_core.node_ports import Ref
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.provider_cache import CacheSpec, ProviderCache
from grafy_core.runtime.artifact_values import inline_model_artifact
from grafy_core.text_regions import (
    TextReading,
    TextRecognizer,
    TextRegion,
    TiffPage,
    TiffPageOpener,
)
from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.paddle_recognizer import PADDLE_MODEL
from grafy_workbench.ocr.tiff_label_crop import read_label_crop
from grafy_workbench.ocr.text_regions import TiffPixelWindow, TiffTextRegions


class TiffRecognizedRegion(TextRegion):
    reading: TextReading | None


class TiffRecognizedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Ref[TiffFile]
    window: TiffPixelWindow
    regions: list[TiffRecognizedRegion]


_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
_PADDLE_DEPLOYMENT = "paddle.ai-test-ihpan"
_CROP_VERSION = "label-crop@1"
_READING_CODEC: TypeAdapter[TextReading] = TypeAdapter(TextReading)


def _paddle_spec(ttl_seconds: int) -> CacheSpec[TextReading]:
    return CacheSpec(
        operation="ocr.paddle.recognize_crop",
        deployment=_PADDLE_DEPLOYMENT,
        revision=PADDLE_MODEL,
        schema_version=1,
        codec=_READING_CODEC,
        ttl_seconds=ttl_seconds,
    )


def _crop_request(png: bytes) -> JsonValue:
    return {
        "crop_sha256": hashlib.sha256(png).hexdigest(),
        "recognizer": PADDLE_MODEL,
        "preprocessing": _CROP_VERSION,
        "options": {},
    }


OCR.register_service_contract(TextRecognizer)
OCR.register(
    inline_model_artifact(
        ArtifactTypeSpec(
            key=ArtifactTypeKey("ocr.tiff_recognized_text", 1),
            title="Recognized TIFF text",
            payload_schema=cast(JsonObject, TiffRecognizedText.model_json_schema()),
            references=(
                ArtifactReferenceContract(
                    path=("source",), target=TIFF_FILE.key, shape="one"
                ),
            ),
        ),
        TiffRecognizedText,
    )
)


async def _prepare(
    page: TiffPage, region: TextRegion
) -> bytes | None | UserFacingNodeError:
    # A normal crop failure stays a user-facing error rather than being hidden in
    # TaskGroup's ExceptionGroup. Unexpected failures still cancel sibling reads.
    try:
        return await read_label_crop(page, region.polygon)
    except UserFacingNodeError as exc:
        return exc


class RecognizeInput(NodeInput):
    regions: TiffTextRegions = Field(title="Text regions")
    recognizer: TextRecognizer = Field(title="Recognizer")


class RecognizeOutput(NodeOutput):
    text: TiffRecognizedText = Field(title="Recognized text")


@OCR.node(
    operator_id="ocr.recognize_tiff_text",
    version=1,
    title="Read detected TIFF text",
    factory=lambda context: ReadTiffTextNode(
        context.open_tiff_page,
        cache=context.provider_cache,
        cache_ttl_seconds=context.provider_cache_ttl_seconds,
    ),
)
@final
class ReadTiffTextNode(Node[NoConfig, RecognizeInput, RecognizeOutput]):
    def __init__(
        self,
        open_page: TiffPageOpener | None,
        *,
        cache: ProviderCache | None = None,
        cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self._open_page = open_page
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    async def _recognize_crops(
        self,
        context: NodeExecutionContext,
        recognizer: TextRecognizer,
        pngs: Sequence[bytes],
        hits: list[bool],
    ) -> list[TextReading]:
        cache = self._cache
        if cache is None:
            raise RuntimeError("crop recognition cache is unset")

        async def compute(missing: Sequence[int]) -> list[TextReading]:
            readings = await recognizer.recognize([pngs[index] for index in missing])
            if len(readings) != len(missing):
                raise UserFacingNodeError(
                    "Text recognizer returned the wrong number of readings"
                )
            return list(readings)

        found = await cache.get_or_compute_many(
            context.workspace_id,
            _paddle_spec(self._cache_ttl_seconds),
            [_crop_request(png) for png in pngs],
            compute,
        )
        readings: list[TextReading] = []
        for reading, hit in found:
            hits.append(hit)
            readings.append(reading)
        return readings

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: RecognizeInput,
        /,
    ) -> RecognizeOutput:
        detected = inputs.regions
        regions: list[TiffRecognizedRegion] = []
        total = len(detected.regions)
        if total:
            if self._open_page is None:
                raise UserFacingNodeError("TIFF window reading is unavailable")
            await context.progress("Reading labels", current=0, total=total)
            page = await self._open_page(
                context.workspace_id,
                detected.source.artifact_id,
                page=detected.window.page,
            )
            hits: list[bool] = []
            for batch in batched(detected.regions, 8):
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(_prepare(page, item)) for item in batch]
                crops = [task.result() for task in tasks]
                for crop in crops:
                    if isinstance(crop, UserFacingNodeError):
                        raise crop
                if self._cache is None:
                    pngs = [crop for crop in crops if isinstance(crop, bytes)]
                    readings: list[TextReading] = (
                        await inputs.recognizer.recognize(pngs) if pngs else []
                    )
                    if len(readings) != len(pngs):
                        raise UserFacingNodeError(
                            "Text recognizer returned the wrong number of readings"
                        )
                    ordered = iter(readings)
                    for region, crop in zip(batch, crops, strict=True):
                        regions.append(
                            TiffRecognizedRegion(
                                polygon=region.polygon,
                                text=region.text,
                                score=region.score,
                                reading=(
                                    next(ordered) if isinstance(crop, bytes) else None
                                ),
                            )
                        )
                else:
                    pngs = [crop for crop in crops if isinstance(crop, bytes)]
                    if pngs:
                        recognized = await self._recognize_crops(
                            context, inputs.recognizer, pngs, hits
                        )
                    else:
                        recognized = []
                    ordered = iter(recognized)
                    for region, crop in zip(batch, crops, strict=True):
                        regions.append(
                            TiffRecognizedRegion(
                                polygon=region.polygon,
                                text=region.text,
                                score=region.score,
                                reading=(
                                    next(ordered) if isinstance(crop, bytes) else None
                                ),
                            )
                        )
                await context.progress(
                    "Reading labels", current=len(regions), total=total
                )
            context.output_metadata["tiff_cache_hits"] = sum(hits)
        return RecognizeOutput(
            text=TiffRecognizedText(
                source=detected.source, window=detected.window, regions=regions
            )
        )
