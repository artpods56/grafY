"""Plan native TIFF reads and reconcile detections in source-page pixels."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor

from pydantic import JsonValue, TypeAdapter
from shapely import (
    Polygon,
    STRtree,
    make_valid,  # pyright: ignore[reportUnknownVariableType]
)
from shapely.geometry.base import BaseGeometry

from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.provider_cache import CacheSpec, ProviderCache
from grafy_core.text_regions import TextDetector, TextRegion, TiffPage
from grafy_workbench.ocr.craft import CRAFT_MODEL

_READ_EDGE = 1000
_CONTEXT = 200
_CORE_EDGE = _READ_EDGE - 2 * _CONTEXT
_MAX_READS = 1024
_MAX_REPAIRS = 32
_PARALLEL_READS = 16
_EDGE_TOLERANCE = 4
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
_CRAFT_DEPLOYMENT = "craft.ai-test-ihpan"
_PNG_VERSION = "window-png@1"
_REGION_CODEC: TypeAdapter[list[TextRegion]] = TypeAdapter(list[TextRegion])


@dataclass(frozen=True, slots=True)
class Window:
    col: int
    row: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.col + self.width

    @property
    def bottom(self) -> int:
        return self.row + self.height

    def with_context(self, page: TiffPage) -> Window:
        col = max(0, self.col - _CONTEXT)
        row = max(0, self.row - _CONTEXT)
        return Window(
            col,
            row,
            min(page.width, self.right + _CONTEXT) - col,
            min(page.height, self.bottom + _CONTEXT) - row,
        )

    def contains(self, x: float, y: float) -> bool:
        return self.col <= x < self.right and self.row <= y < self.bottom


def _plan(area: Window, page: TiffPage, single: bool) -> list[Window]:
    if area.right > page.width or area.bottom > page.height:
        raise UserFacingNodeError("The selection extends beyond the TIFF page")
    if single:
        if area.width * area.height > _READ_EDGE**2:
            raise UserFacingNodeError(
                "Single crop supports at most 1,000,000 pixels. Choose Automatic to scan this area."
            )
        return [area]

    # Tiles start on the page grid. A selection that moves inside the same tiles
    # keeps the same windows, so the cache key does not move with the pointer.
    first_col = (area.col // _CORE_EDGE) * _CORE_EDGE
    first_row = (area.row // _CORE_EDGE) * _CORE_EDGE
    cols = ceil((area.right - first_col) / _CORE_EDGE)
    rows = ceil((area.bottom - first_row) / _CORE_EDGE)
    if cols * rows > _MAX_READS:
        raise UserFacingNodeError(
            f"This scan requires more than {_MAX_READS} reads. Select a smaller area."
        )
    return [
        Window(
            col,
            row,
            min(_CORE_EDGE, page.width - col),
            min(_CORE_EDGE, page.height - row),
        ).with_context(page)
        for row in range(first_row, area.bottom, _CORE_EDGE)
        for col in range(first_col, area.right, _CORE_EDGE)
    ]


def _craft_spec(ttl_seconds: int) -> CacheSpec[list[TextRegion]]:
    return CacheSpec(
        operation="ocr.craft.detect_window",
        deployment=_CRAFT_DEPLOYMENT,
        revision=CRAFT_MODEL,
        schema_version=1,
        codec=_REGION_CODEC,
        ttl_seconds=ttl_seconds,
    )


def _craft_request(page: TiffPage, window: Window) -> JsonValue:
    return {
        "source_sha256": page.source_sha256,
        "page": page.page,
        "window": [window.col, window.row, window.width, window.height],
        "png": _PNG_VERSION,
        "detect": {"core_edge": _CORE_EDGE, "context": _CONTEXT},
    }


def _progress_message(message: str, hits: list[bool]) -> str:
    cached = sum(hits)
    if cached == 0:
        return message
    return f"{message} · {cached} cached"


async def _detect(
    context: NodeExecutionContext,
    page: TiffPage,
    detector: TextDetector,
    window: Window,
    *,
    cache: ProviderCache | None,
    cache_ttl_seconds: int,
    hits: list[bool],
) -> list[TextRegion]:
    async def compute() -> list[TextRegion]:
        png = await page.read(
            col=window.col, row=window.row, width=window.width, height=window.height
        )
        try:
            return await detector.detect(png, width=window.width, height=window.height)
        except UserFacingNodeError as exc:
            raise UserFacingNodeError(
                f"TIFF window at ({window.col}, {window.row}): {exc}"
            ) from exc

    if cache is None:
        local_regions = await compute()
    else:
        local_regions, hit = await cache.get_or_compute(
            context.workspace_id,
            _craft_spec(cache_ttl_seconds),
            _craft_request(page, window),
            compute,
        )
        hits.append(hit)

    regions: list[TextRegion] = []
    for region in local_regions:
        if any(x > window.width or y > window.height for x, y in region.polygon):
            raise UserFacingNodeError(
                "Text detector returned a polygon outside the window"
            )
        regions.append(
            TextRegion(
                polygon=[(x + window.col, y + window.row) for x, y in region.polygon],
                text=region.text,
                score=region.score,
            )
        )
    return regions


async def _detect_many(
    context: NodeExecutionContext,
    page: TiffPage,
    detector: TextDetector,
    windows: Sequence[Window],
    message: str,
    *,
    cache: ProviderCache | None,
    cache_ttl_seconds: int,
    hits: list[bool],
) -> dict[Window, list[TextRegion]]:
    if not windows:
        return {}
    remaining = iter(windows)
    results: dict[Window, list[TextRegion]] = {}
    await context.progress(message, current=0, total=len(windows))

    async def worker() -> None:
        for window in remaining:
            results[window] = await _detect(
                context,
                page,
                detector,
                window,
                cache=cache,
                cache_ttl_seconds=cache_ttl_seconds,
                hits=hits,
            )
            await context.progress(
                _progress_message(message, hits),
                current=len(results),
                total=len(windows),
            )

    tasks = [
        asyncio.create_task(worker()) for _ in range(min(_PARALLEL_READS, len(windows)))
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # Completion order must not decide ties between two identical predictions.
    return {window: results[window] for window in windows}


@dataclass(frozen=True, slots=True)
class _Candidate:
    region: TextRegion
    window: Window
    polygon: BaseGeometry
    center: tuple[float, float]
    clearance: float

    @property
    def clipped(self) -> bool:
        return self.clearance <= _EDGE_TOLERANCE


def _candidates(
    page: TiffPage, detections: dict[Window, list[TextRegion]]
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for window, regions in detections.items():
        for region in regions:
            polygon = Polygon(region.polygon)
            shape = polygon if polygon.is_valid else make_valid(polygon)
            if shape.area <= 0:
                continue
            left, top, right, bottom = shape.bounds
            # Actual page edges cannot be repaired by another read.
            clearance = min(
                left - window.col if window.col else float("inf"),
                top - window.row if window.row else float("inf"),
                window.right - right if window.right < page.width else float("inf"),
                window.bottom - bottom if window.bottom < page.height else float("inf"),
            )
            candidates.append(
                _Candidate(
                    region,
                    window,
                    shape,
                    ((left + right) / 2, (top + bottom) / 2),
                    clearance,
                )
            )
    return candidates


def _deduplicate(candidates: list[_Candidate]) -> list[_Candidate]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            item.clipped,
            -item.clearance,
            -(item.region.score if item.region.score is not None else -1),
            -item.polygon.area,
        ),
    )
    tree = STRtree([item.polygon for item in ranked])
    suppressed: set[int] = set()
    kept: list[_Candidate] = []
    for index, item in enumerate(ranked):
        if index in suppressed:
            continue
        kept.append(item)
        for hit in tree.query(item.polygon):
            other_index = int(hit)
            if other_index <= index or other_index in suppressed:
                continue
            other = ranked[other_index]
            if item.window == other.window:
                continue
            area = item.polygon.intersection(other.polygon).area
            union = item.polygon.area + other.polygon.area - area
            # A seam fragment can be mostly contained while having very low IoU.
            if area / union >= 0.65 or (
                other.clipped and not item.clipped and area / other.polygon.area >= 0.8
            ):
                suppressed.add(other_index)
    return kept


def _repair_windows(
    page: TiffPage, area: Window, candidates: list[_Candidate], seen: set[Window]
) -> list[Window]:
    repairs: list[Window] = []
    for candidate in candidates:
        x, y = candidate.center
        if not candidate.clipped or not area.contains(x, y):
            continue
        # Snap nearby fragments to the same repair read to avoid repeating work.
        step = _CONTEXT // 2
        width = min(page.width, _READ_EDGE)
        height = min(page.height, _READ_EDGE)
        col = min(max(0, floor(x / step) * step - width // 2), page.width - width)
        row = min(max(0, floor(y / step) * step - height // 2), page.height - height)
        window = Window(col, row, width, height)
        if window in seen:
            continue
        seen.add(window)
        repairs.append(window)
        if len(repairs) == _MAX_REPAIRS:
            break
    return repairs


async def detect_area(
    context: NodeExecutionContext,
    page: TiffPage,
    detector: TextDetector,
    area: Window,
    *,
    single: bool,
    cache: ProviderCache | None = None,
    cache_ttl_seconds: int = _CACHE_TTL_SECONDS,
) -> list[TextRegion]:
    hits: list[bool] = []
    windows = _plan(area, page, single)
    detections = await _detect_many(
        context,
        page,
        detector,
        windows,
        "Detecting text in TIFF windows",
        cache=cache,
        cache_ttl_seconds=cache_ttl_seconds,
        hits=hits,
    )
    context.output_metadata["tiff_reads"] = len(windows)
    if single:
        context.output_metadata["tiff_cache_hits"] = sum(hits)
        return detections[area]

    candidates = _candidates(page, detections)
    merged = _deduplicate(candidates)
    repairs = _repair_windows(page, area, merged, set(windows))
    if repairs:
        retry = await _detect_many(
            context,
            page,
            detector,
            repairs,
            "Checking labels at window edges",
            cache=cache,
            cache_ttl_seconds=cache_ttl_seconds,
            hits=hits,
        )
        merged = _deduplicate([*candidates, *_candidates(page, retry)])

    selected = [item for item in merged if area.contains(*item.center)]
    context.output_metadata["tiff_cache_hits"] = sum(hits)
    context.output_metadata["tiff_seam_reads"] = len(repairs)
    context.output_metadata["tiff_edge_candidates"] = sum(
        item.clipped for item in selected
    )
    return [
        item.region for item in sorted(selected, key=lambda item: item.center[::-1])
    ]
