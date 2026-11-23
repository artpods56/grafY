"""Read the text of already localized TIFF regions."""

import asyncio
import hashlib
from collections.abc import Sequence
from itertools import batched
from typing import cast, final, override

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from grafy_core.artifacts import (
    ArtifactPreviewKind,
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
from grafy_workbench.ocr.progress import cached_progress
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
_CROP_VERSION = "label-crop@1"
_READING_CODEC: TypeAdapter[TextReading] = TypeAdapter(TextReading)


def _recognizer_spec(
    ttl_seconds: int, deployment: str, revision: str
) -> CacheSpec[TextReading]:
    """Cache one crop reading for the configured recognizer."""

    return CacheSpec(
        operation="ocr.crop_reader.recognize_crop",
        deployment=deployment,
        revision=revision,
        schema_version=1,
        codec=_READING_CODEC,
        ttl_seconds=ttl_seconds,
    )


def _crop_request(
    png: bytes, revision: str, options: dict[str, JsonValue]
) -> JsonValue:
    """What a reading depends on, and nothing that merely describes the work.

    The crop enters as a digest because those pixels are what the model is shown: any
    change to the mask, the deskew, or the scaling re-cuts them and moves the digest,
    so no older answer is ever served for a different crop. A timeout and a retry
    count are absent on purpose — they bound how long the provider may take, never
    what it answers.
    """

    return {
        "crop_sha256": hashlib.sha256(png).hexdigest(),
        "recognizer": revision,
        "preprocessing": _CROP_VERSION,
        "options": options,
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
            preview_kind=ArtifactPreviewKind.TIFF_TEXT,
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


def _checked(readings: Sequence[TextReading], asked: int) -> list[TextReading]:
    """One reading per crop, or the failure that says the recognizer miscounted."""

    if len(readings) != asked:
        raise UserFacingNodeError(
            "Text recognizer returned the wrong number of readings"
        )
    return list(readings)


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
    """Read text from detected TIFF regions."""

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

    async def _recognize(
        self,
        context: NodeExecutionContext,
        recognizer: TextRecognizer,
        pngs: Sequence[bytes],
        hits: list[bool],
    ) -> list[TextReading]:
        """One reading per crop in order, with the provider called only for the misses.

        Every crop of a step goes out in one request, cached or not, which is what
        keeps the recognizer's own batching and its one-batch-at-a-time slot intact.
        """

        cache = self._cache
        identity = recognizer.cache_identity()
        if cache is None or identity.revision is None:
            return _checked(await recognizer.recognize(list(pngs)), len(pngs))

        async def compute(missing: Sequence[int]) -> list[TextReading]:
            # Only the misses go out, and a crop repeated within the step is asked
            # for once, so the count to match is the misses, not the whole step.
            crops = [pngs[index] for index in missing]
            return _checked(await recognizer.recognize(crops), len(missing))

        found = await cache.get_or_compute_many(
            context.workspace_id,
            _recognizer_spec(
                self._cache_ttl_seconds, identity.deployment, identity.revision
            ),
            [
                _crop_request(png, identity.revision, identity.options_payload())
                for png in pngs
            ],
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
            crops = 0
            for batch in batched(detected.regions, 8):
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(_prepare(page, item)) for item in batch]
                prepared = [task.result() for task in tasks]
                for crop in prepared:
                    if isinstance(crop, UserFacingNodeError):
                        raise crop
                pngs = [crop for crop in prepared if isinstance(crop, bytes)]
                crops += len(pngs)
                recognized: list[TextReading] = []
                if pngs:
                    recognized = await self._recognize(
                        context, inputs.recognizer, pngs, hits
                    )
                ordered = iter(recognized)
                for region, crop in zip(batch, prepared, strict=True):
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
                    cached_progress("Reading labels", hits),
                    current=len(regions),
                    total=total,
                )
            context.output_metadata["tiff_crops"] = crops
            context.output_metadata["tiff_cache_hits"] = sum(hits)
        return RecognizeOutput(
            text=TiffRecognizedText(
                source=detected.source, window=detected.window, regions=regions
            )
        )
