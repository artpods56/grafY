"""Classify detected TIFF regions in their map context."""

import asyncio
from base64 import b64encode
from hashlib import sha256
from io import BytesIO
from math import ceil, floor, isclose
from typing import Annotated, Literal, Self, final, override
from uuid import uuid4

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.contracts.ocr import PixelPolygon, TextRegion, TiffPage, TiffPageOpener
from grafy_core.credential_verification import unsupported_credential_verifier
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.node_context import UserFacingNodeError
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import (
    NodeHttpEgressContract,
    NodeSecretInput,
)
from grafy_core.provider_cache import CacheSpec, ProviderCache
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType
from PIL import Image, ImageDraw, ImageOps
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

import grafy_workbench.table.plugin as _table_plugin
from grafy_plugin_map_toponyms.declaration import MAP_TOPONYMS
from grafy_core.provider_http import ProviderRequest, post_json
from grafy_plugin_map_toponyms.text_regions import TiffTextRegions

_ = _table_plugin.__name__

JEV_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-1.14.0"
_JEV_DEPLOYMENT = "jev.typesafe-ai"
_CROP_VERSION = "jev-context-crop@1"
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
_MIN_IMAGE_EDGE = 280
_MAX_IMAGE_EDGE = 1568
_PROGRESS = "Classifying TIFF regions with Visual Jev"
_ADVANCED: dict[str, JsonValue] = {"x-grafy-advanced": True}


def _cached_progress(message: str, hits: list[bool]) -> str:
    cached = sum(hits)
    return message if cached == 0 else f"{message} · {cached} cached"


type _Kind = Literal[
    "settlement_or_place_name",
    "other_text",
    "trees_or_vegetation",
    "other_symbol_or_artifact",
]
type _Probability = Annotated[float, Field(strict=True, ge=0, le=1)]

KINDS: dict[_Kind, str] = {
    "settlement_or_place_name": (
        "A village, town, or settlement name, or its written prefix, for example сел:, Д:, or с:."
    ),
    "other_text": (
        "A river or stream label (реч:), a parcel number (64, 97), terrain text, "
        "or a fragment of handwriting or printed text without a clear settlement identification."
    ),
    "trees_or_vegetation": "Hand-drawn trees, tree rows, bushes, or forest symbols.",
    "other_symbol_or_artifact": "Hatching, roads, buildings, borders, smudges, or other non-text drawings.",
}

_QUESTIONS = {
    "is_text": {
        "type": "noul",
        "instructions": (
            "In `map_image`, does the magenta-outlined region contain handwritten or printed map text, "
            "abbreviations, or numerals (e.g. 18th-century Russian cursive settlement names, "
            "сел:, реч:, Д:, parcel numbers), rather than trees, bushes, hatching, roads, "
            "borders, or artifacts? Count text fragments. Judge only the map marks "
            "inside the outline, ignoring the overlay and nearby labels outside it."
        ),
    },
    "kind": {
        "type": "choice",
        "instructions": (
            "In `map_image`, which option best describes the map marks inside the magenta-outlined region? "
            "Ignore the overlay and nearby labels outside the outline."
        ),
        "criteria": KINDS,
    },
}

_SCORE_COLUMNS = (
    ("region_index", "Region index", TableValueType.INTEGER),
    ("page", "TIFF page", TableValueType.INTEGER),
    ("x", "Left pixel", TableValueType.NUMBER),
    ("y", "Top pixel", TableValueType.NUMBER),
    ("width", "Width in pixels", TableValueType.NUMBER),
    ("height", "Height in pixels", TableValueType.NUMBER),
    ("p_text", "Text probability", TableValueType.NUMBER),
    ("p_is_text", "Jev yes/no text probability", TableValueType.NUMBER),
    ("p_settlement", "Settlement probability", TableValueType.NUMBER),
    ("p_other_text", "Other text probability", TableValueType.NUMBER),
    ("p_trees", "Vegetation probability", TableValueType.NUMBER),
    ("p_other_symbol", "Other symbol probability", TableValueType.NUMBER),
    ("predicted_kind", "Predicted kind", TableValueType.TEXT),
    ("triage_band", "Triage band", TableValueType.TEXT),
    ("uncertainty", "Text uncertainty", TableValueType.NUMBER),
    ("kept", "Kept", TableValueType.BOOLEAN),
)


class FilterTiffJevConfig(NodeConfig):
    min_text_probability: float = Field(
        default=0.45, ge=0, le=1, title="Minimum text probability"
    )
    keep_scope: Literal["All text", "Settlements only"] = Field(
        default="All text", title="Keep"
    )
    auto_drop_threshold: float = Field(
        default=0.15,
        ge=0,
        le=0.5,
        title="Auto-drop threshold",
        json_schema_extra=_ADVANCED,
    )
    prelabel_threshold: float = Field(
        default=0.90,
        ge=0.5,
        le=1,
        title="Prelabel threshold",
        json_schema_extra=_ADVANCED,
    )
    context_padding_px: int = Field(
        default=80,
        ge=16,
        le=256,
        title="Context padding (px)",
        json_schema_extra=_ADVANCED,
    )
    min_crop_edge_px: int = Field(
        default=_MIN_IMAGE_EDGE,
        ge=_MIN_IMAGE_EDGE,
        le=1000,
        title="Minimum crop edge (px)",
        json_schema_extra=_ADVANCED,
    )
    model: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field(
        default=DEFAULT_JEV_MODEL, title="Visual Jev model", json_schema_extra=_ADVANCED
    )
    max_concurrency: int = Field(
        default=4, ge=1, le=8, title="Maximum concurrency", json_schema_extra=_ADVANCED
    )
    timeout_ms: int = Field(
        default=60_000,
        ge=1_000,
        le=900_000,
        title="Time limit (ms)",
        json_schema_extra=_ADVANCED,
    )
    max_retries: int = Field(
        default=2, ge=0, le=5, title="Max retries", json_schema_extra=_ADVANCED
    )


class FilterTiffJevInput(NodeInput):
    regions: TiffTextRegions = Field(title="Text regions")


class FilterTiffJevOutput(NodeOutput):
    regions: TiffTextRegions = Field(title="Filtered text regions")
    scores: Table = Field(title="Region scores")


class _NoulAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    type: Literal["noul"]
    noul: _Probability


class _ChoiceAnswer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    type: Literal["choice"]
    choice: _Kind
    probabilities: dict[_Kind, _Probability]
    confidence: _Probability

    @model_validator(mode="after")
    def _check_distribution(self) -> Self:
        if self.probabilities.keys() != KINDS.keys() or not isclose(
            sum(self.probabilities.values()), 1.0, abs_tol=0.005
        ):
            raise ValueError(
                "Expected a probability distribution over the four region kinds"
            )
        return self


class _Answers(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    is_text: _NoulAnswer
    kind: _ChoiceAnswer


class _JevResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    answers: _Answers


class _JevVerdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    is_text: _Probability
    predicted_kind: _Kind
    probabilities: dict[_Kind, _Probability]


_VERDICT_CODEC: TypeAdapter[_JevVerdict] = TypeAdapter(_JevVerdict)


def _crop_axis(
    lo: float, hi: float, limit: int, config: FilterTiffJevConfig
) -> tuple[int, int]:
    first = floor(lo) - config.context_padding_px
    last = ceil(hi) + config.context_padding_px + 1
    size = min(limit, max(config.min_crop_edge_px, last - first))
    start = min(max(0, (first + last - size) // 2), limit - size)
    return start, size


def _marked_png(png: bytes, polygon: PixelPolygon, col: int, row: int) -> bytes:
    try:
        with Image.open(BytesIO(png)) as source:
            crop = source.convert("RGB")
    except (OSError, Image.DecompressionBombError):
        raise UserFacingNodeError(
            "Could not decode the TIFF window for Visual Jev"
        ) from None

    points = [(x - col, y - row) for x, y in polygon]
    ImageDraw.Draw(crop).line(
        [*points, points[0]], fill="#ff00ff", width=2, joint="curve"
    )
    # Small pages cannot supply the minimum image size in native pixels.
    pad_x = max(0, _MIN_IMAGE_EDGE - crop.width)
    pad_y = max(0, _MIN_IMAGE_EDGE - crop.height)
    if pad_x or pad_y:
        crop = ImageOps.expand(
            crop,
            (pad_x // 2, pad_y // 2, (pad_x + 1) // 2, (pad_y + 1) // 2),
            fill="white",
        )
    result = BytesIO()
    crop.save(result, format="PNG")
    return result.getvalue()


async def _read_crop(
    page: TiffPage, polygon: PixelPolygon, config: FilterTiffJevConfig
) -> bytes:
    xs, ys = zip(*polygon, strict=True)
    if max(xs) > page.width or max(ys) > page.height:
        raise UserFacingNodeError("A text polygon extends outside its source TIFF page")
    col, width = _crop_axis(min(xs), max(xs), page.width, config)
    row, height = _crop_axis(min(ys), max(ys), page.height, config)
    if max(width, height) > _MAX_IMAGE_EDGE:
        raise UserFacingNodeError(
            "A TIFF crop exceeds Visual Jev's 1568-pixel edge limit"
        )
    png = await page.read(col=col, row=row, width=width, height=height)
    return await asyncio.to_thread(_marked_png, png, polygon, col, row)


async def _query_jev(
    png: bytes, api_key: SecretStr, config: FilterTiffJevConfig
) -> _JevVerdict:
    ref = str(uuid4())
    body = await post_json(
        ProviderRequest(
            service="Visual Jev",
            url=JEV_URL,
            payload={
                "model": config.model,
                "state": {"map_image": ref},
                "assets": {
                    ref: {
                        "type": "image",
                        "format": "png",
                        "data_base64": b64encode(png).decode("ascii"),
                    }
                },
                "questions": _QUESTIONS,
            },
            api_key=api_key,
            attempts=config.max_retries + 1,
            timeout_seconds=config.timeout_ms / 1_000,
            max_response_bytes=64 * 1024,
            extra_headers=(("TypeSafe-Danger-Zone-Images", "true"),),
            connection_route=None,
        )
    )
    try:
        answers = _JevResponse.model_validate_json(body).answers
    except ValidationError:
        raise UserFacingNodeError("Visual Jev returned invalid region scores") from None
    return _JevVerdict(
        is_text=answers.is_text.noul,
        predicted_kind=answers.kind.choice,
        probabilities=answers.kind.probabilities,
    )


def _score_region(
    index: int,
    page: int,
    region: TextRegion,
    verdict: _JevVerdict,
    config: FilterTiffJevConfig,
) -> dict[str, TableValue]:
    xs, ys = zip(*region.polygon, strict=True)
    p_settlement = verdict.probabilities["settlement_or_place_name"]
    p_other_text = verdict.probabilities["other_text"]
    p_text = min(1.0, p_settlement + p_other_text)
    score = p_text if config.keep_scope == "All text" else p_settlement
    band = "review"
    if p_text <= config.auto_drop_threshold:
        band = "auto_drop"
    elif p_text >= config.prelabel_threshold:
        band = "prelabel"

    return {
        "region_index": index,
        "page": page,
        "x": min(xs),
        "y": min(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
        "p_text": p_text,
        "p_is_text": verdict.is_text,
        "p_settlement": p_settlement,
        "p_other_text": p_other_text,
        "p_trees": verdict.probabilities["trees_or_vegetation"],
        "p_other_symbol": verdict.probabilities["other_symbol_or_artifact"],
        "predicted_kind": verdict.predicted_kind,
        "triage_band": band,
        "uncertainty": 1.0 - abs(2.0 * p_text - 1.0),
        "kept": score >= config.min_text_probability,
    }


@MAP_TOPONYMS.node(
    operator_id="ocr.filter_tiff_jev",
    version=1,
    title="Filter TIFF regions with Visual Jev",
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    http_egress=NodeHttpEgressContract(fixed_destinations=("https://api.typesafe.ai",)),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="TypeSafe AI (Jev) API key",
            provider_kind="jev",
            verifier=unsupported_credential_verifier(
                "This key will be checked on first run."
            ),
        ),
    ),
    factory=lambda context: FilterTiffJevNode(
        context.open_tiff_page,
        cache=context.provider_cache,
        cache_ttl_seconds=context.provider_cache_ttl_seconds,
    ),
)
@final
class FilterTiffJevNode(
    Node[FilterTiffJevConfig, FilterTiffJevInput, FilterTiffJevOutput]
):
    """Filter TIFF text regions with Jev."""

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

    async def _classify(
        self,
        context: NodeExecutionContext,
        config: FilterTiffJevConfig,
        detected: TiffTextRegions,
    ) -> list[_JevVerdict]:
        if self._open_page is None:
            raise UserFacingNodeError("TIFF window reading is unavailable")
        api_key = await context.secrets.require("api_key")
        page = await self._open_page(
            context.workspace_id, detected.source.artifact_id, page=detected.window.page
        )
        spec = CacheSpec(
            operation="ocr.jev.classify_crop",
            deployment=_JEV_DEPLOYMENT,
            revision=config.model,
            schema_version=1,
            codec=_VERDICT_CODEC,
            ttl_seconds=self._cache_ttl_seconds,
        )
        slots = asyncio.Semaphore(config.max_concurrency)
        cache = self._cache

        async def classify(region: TextRegion) -> tuple[_JevVerdict, bool]:
            async with slots:
                png = await _read_crop(page, region.polygon, config)
                if cache is None:
                    return await _query_jev(png, api_key, config), False
                return await cache.get_or_compute(
                    context.workspace_id,
                    spec,
                    {
                        "crop_sha256": sha256(png).hexdigest(),
                        "preprocessing": _CROP_VERSION,
                    },
                    lambda: _query_jev(png, api_key, config),
                )

        total = len(detected.regions)
        hits: list[bool] = []
        await context.progress(_PROGRESS, current=0, total=total)
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(classify(region)) for region in detected.regions
                ]
                for completed in asyncio.as_completed(tasks):
                    _, hit = await completed
                    hits.append(hit)
                    if total <= 16 or len(hits) % 16 == 0 or len(hits) == total:
                        await context.progress(
                            _cached_progress(_PROGRESS, hits),
                            current=len(hits),
                            total=total,
                        )
        except* UserFacingNodeError as errors:
            # The runner recognizes a direct user-facing error.
            for error in errors.exceptions:
                if isinstance(error, UserFacingNodeError):
                    raise error from None
            raise
        return [task.result()[0] for task in tasks]

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: FilterTiffJevConfig,
        inputs: FilterTiffJevInput,
        /,
    ) -> FilterTiffJevOutput:
        detected = inputs.regions
        verdicts = (
            await self._classify(context, config, detected) if detected.regions else []
        )
        rows: list[dict[str, TableValue]] = []
        kept: list[TextRegion] = []
        for index, (region, verdict) in enumerate(
            zip(detected.regions, verdicts, strict=True)
        ):
            row = _score_region(index, detected.window.page, region, verdict, config)
            rows.append(row)
            if row["kept"]:
                kept.append(region)
        return FilterTiffJevOutput(
            regions=TiffTextRegions(
                source=detected.source, window=detected.window, regions=kept
            ),
            scores=Table(
                columns=[
                    TableColumn(id=key, title=title, value_type=value_type)
                    for key, title, value_type in _SCORE_COLUMNS
                ],
                rows=rows,
            ),
        )
