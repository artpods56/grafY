from grafy_core.text_regions import ServiceCacheIdentity
import asyncio
import json
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.provider_cache import InMemoryCacheStore, ProviderCache
from grafy_core.text_regions import TextRegion, TiffPage
from grafy_workbench.ocr.craft import CRAFT_URL, CraftDetector
from grafy_workbench.ocr.tiff_scan import Window, detect_area


class PageReads:
    def __init__(self, width: int, height: int) -> None:
        self.windows: list[Window] = []
        self.page = TiffPage(width, height, self.read, source_sha256="0" * 64, page=0)

    async def read(self, *, col: int, row: int, width: int, height: int) -> bytes:
        self.windows.append(Window(col, row, width, height))
        return json.dumps([col, row, width, height]).encode()


class Labels:
    def cache_identity(self) -> ServiceCacheIdentity:
        return ServiceCacheIdentity("test.labels", "1")

    labels = [
        ("boundary", 350, 270, 440, 350),
        ("outside", 190, 320, 240, 340),
        ("seam", 995, 320, 1200, 340),
        ("nearby", 990, 345, 1180, 365),
        ("needs repair", 900, 372, 1240, 392),
    ]

    async def detect(self, png: bytes, *, width: int, height: int) -> list[TextRegion]:
        col, row, _, _ = json.loads(png)
        regions: list[TextRegion] = []
        for text, left, top, right, bottom in self.labels:
            if text == "needs repair" and col == 400:
                continue
            x0, x1 = max(0, left - col), min(width, right - col)
            y0, y1 = max(0, top - row), min(height, bottom - row)
            if x0 < x1 and y0 < y1:
                regions.append(
                    TextRegion(
                        text=text,
                        polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                    )
                )
        return regions


class ScanProgress:
    def __init__(self) -> None:
        self.updates: list[tuple[str, int | None, int | None]] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        self.updates.append((message, current, total))


async def test_overlaps_replace_fragments_and_keep_labels_whole_at_selection_edge():
    source = PageReads(1800, 900)
    reporter = ScanProgress()
    context = NodeExecutionContext(
        workspace_id=uuid4(), node_id="detect", progress_reporter=reporter
    )

    results = await detect_area(
        context, source.page, Labels(), Window(300, 300, 1200, 100), single=False
    )

    assert source.windows == [
        Window(0, 0, 800, 800),
        Window(400, 0, 1000, 800),
        Window(1000, 0, 800, 800),
        Window(600, 0, 1000, 900),
    ]
    assert [(item.text, item.polygon[0], item.polygon[2]) for item in results] == [
        ("boundary", (350, 270), (440, 350)),
        ("seam", (995, 320), (1200, 340)),
        ("nearby", (990, 345), (1180, 365)),
        ("needs repair", (900, 372), (1240, 392)),
    ]
    assert reporter.updates == [
        ("Detecting text in TIFF windows", 0, 3),
        ("Detecting text in TIFF windows", 1, 3),
        ("Detecting text in TIFF windows", 2, 3),
        ("Detecting text in TIFF windows", 3, 3),
        ("Checking labels at window edges", 0, 1),
        ("Checking labels at window edges", 1, 1),
    ]
    assert context.output_metadata == {
        "tiff_reads": 3,
        "tiff_cache_hits": 0,
        "tiff_seam_reads": 1,
        "tiff_edge_candidates": 0,
    }


async def test_whole_page_reads_stop_at_real_edges_and_run_sixteen_at_a_time():
    source = PageReads(4000, 2600)
    context = NodeExecutionContext(workspace_id=uuid4(), node_id="detect")
    first_batch = asyncio.Event()
    release_batch = asyncio.Event()

    class Detector:
        def cache_identity(self):
            return ServiceCacheIdentity("test", "1")

        concurrent = 0

        async def detect(
            self, png: bytes, *, width: int, height: int
        ) -> list[TextRegion]:
            self.concurrent += 1
            if self.concurrent == 16:
                first_batch.set()
            try:
                await release_batch.wait()
            finally:
                self.concurrent -= 1
            return []

    detector = Detector()
    task = asyncio.create_task(
        detect_area(
            context, source.page, detector, Window(0, 0, 4000, 2600), single=False
        )
    )
    try:
        await first_batch.wait()
        assert len(source.windows) == 16
    finally:
        release_batch.set()
        await task

    assert len(source.windows) == 35
    assert source.windows[-1] == Window(3400, 2200, 600, 400)
    assert all(read.width * read.height <= 1_000_000 for read in source.windows)
    assert detector.concurrent == 0


@pytest.mark.parametrize(
    ("area", "message"),
    [
        (Window(0, 0, 1500, 1000), "Single crop supports at most"),
        (Window(0, 0, 1801, 900), "extends beyond the TIFF page"),
    ],
)
async def test_invalid_single_crop_fails_before_reading(area: Window, message: str):
    source = PageReads(1800, 1200)
    context = NodeExecutionContext(workspace_id=uuid4(), node_id="detect")
    with pytest.raises(UserFacingNodeError, match=message):
        await detect_area(context, source.page, Labels(), area, single=True)
    assert source.windows == []


def test_craft_cache_deployment_names_the_route_host() -> None:
    assert urlsplit(CRAFT_URL).hostname == "ai-test.ihpan.edu.pl"
    detector = CraftDetector(
        SecretStr("test"),
        timeout_ms=1000,
        max_retries=0,
        text_threshold=0.7,
        link_threshold=0.4,
        low_text=0.3,
    )
    assert detector.cache_identity().deployment == "craft.ai-test-ihpan"


class CountingDetector:
    def cache_identity(self):
        return ServiceCacheIdentity("test", "1", getattr(self, "request_options", {}))

    def __init__(self) -> None:
        self.calls = 0

    async def detect(self, png: bytes, *, width: int, height: int) -> list[TextRegion]:
        del png, width, height
        self.calls += 1
        return []


def _page(width: int, height: int, digest: str) -> PageReads:
    source = PageReads(width, height)
    source.page = replace(source.page, source_sha256=digest)
    return source


async def _cached_scan(
    source: PageReads,
    detector: CountingDetector,
    area: Window,
    cache: ProviderCache,
    workspace_id: UUID,
) -> NodeExecutionContext:
    context = NodeExecutionContext(workspace_id=workspace_id, node_id="detect")
    await detect_area(context, source.page, detector, area, single=False, cache=cache)
    return context


async def test_a_second_scan_of_an_unchanged_selection_makes_no_provider_calls():
    source = _page(1800, 900, "1" * 64)
    detector = CountingDetector()
    cache = ProviderCache(InMemoryCacheStore())
    workspace_id = uuid4()
    area = Window(300, 300, 1200, 100)

    await _cached_scan(source, detector, area, cache, workspace_id)
    calls = detector.calls
    reads = len(source.windows)
    assert calls > 0
    context = await _cached_scan(source, detector, area, cache, workspace_id)

    assert detector.calls == calls
    assert len(source.windows) == reads
    assert context.output_metadata["tiff_cache_hits"] == calls


async def test_a_one_pixel_selection_move_stays_on_the_same_tiles():
    source = _page(1800, 900, "1" * 64)
    detector = CountingDetector()
    cache = ProviderCache(InMemoryCacheStore())
    workspace_id = uuid4()

    await _cached_scan(
        source, detector, Window(300, 300, 1200, 100), cache, workspace_id
    )
    calls = detector.calls
    reads = len(source.windows)
    await _cached_scan(
        source, detector, Window(301, 301, 1200, 100), cache, workspace_id
    )

    assert detector.calls == calls
    assert len(source.windows) == reads


async def test_a_reupload_with_different_bytes_scans_again():
    detector = CountingDetector()
    cache = ProviderCache(InMemoryCacheStore())
    workspace_id = uuid4()
    area = Window(300, 300, 1200, 100)
    first = _page(1800, 900, "1" * 64)
    second = _page(1800, 900, "2" * 64)

    await _cached_scan(first, detector, area, cache, workspace_id)
    calls = detector.calls
    await _cached_scan(second, detector, area, cache, workspace_id)

    assert calls > 0
    assert detector.calls == calls * 2


class TunedDetector(CountingDetector):
    def __init__(self, options: dict[str, float]) -> None:
        super().__init__()
        self.request_options = options


async def test_detector_request_options_are_part_of_the_provider_cache_key():
    source = _page(1800, 900, "1" * 64)
    cache = ProviderCache(InMemoryCacheStore())
    workspace_id = uuid4()
    area = Window(300, 300, 1200, 100)

    plain = CountingDetector()
    await _cached_scan(source, plain, area, cache, workspace_id)

    tuned = TunedDetector({"text_threshold": 0.85})
    context = await _cached_scan(source, tuned, area, cache, workspace_id)
    assert tuned.calls == plain.calls
    assert context.output_metadata["tiff_cache_hits"] == 0

    retuned = TunedDetector({"text_threshold": 0.85})
    context = await _cached_scan(source, retuned, area, cache, workspace_id)
    assert retuned.calls == 0
    assert context.output_metadata["tiff_cache_hits"] == tuned.calls


async def test_whole_sheet_scan_accepts_the_largest_mohilew_sheet() -> None:
    source = PageReads(21208, 17752)
    detector = Labels()
    detector.labels = []

    assert (
        await detect_area(
            NodeExecutionContext(workspace_id=uuid4()),
            source.page,
            detector,
            Window(0, 0, 21208, 17752),
            single=False,
        )
        == []
    )
    assert len(source.windows) == 1080
    assert source.windows[-1].right == 21208
    assert source.windows[-1].bottom == 17752


async def test_detector_identities_isolate_cache_entries():
    source = _page(100, 100, "a" * 64)
    cache = ProviderCache(InMemoryCacheStore())
    workspace = uuid4()
    area = Window(0, 0, 100, 100)

    class OtherDetector(CountingDetector):
        def cache_identity(self) -> ServiceCacheIdentity:
            return ServiceCacheIdentity("other", "1")

    first, second = CountingDetector(), OtherDetector()
    await _cached_scan(source, first, area, cache, workspace)
    await _cached_scan(source, second, area, cache, workspace)
    await _cached_scan(source, second, area, cache, workspace)
    assert first.calls == 1
    assert second.calls == 1


async def test_detector_moving_revision_bypasses_cache():
    from unittest.mock import AsyncMock

    source = _page(100, 100, "b" * 64)
    cache = ProviderCache(InMemoryCacheStore())
    cache.get_or_compute = AsyncMock(side_effect=AssertionError("cache accessed"))

    class MovingDetector(CountingDetector):
        def cache_identity(self) -> ServiceCacheIdentity:
            return ServiceCacheIdentity("moving", None)

    detector = MovingDetector()
    await _cached_scan(source, detector, Window(0, 0, 100, 100), cache, uuid4())
    assert detector.calls == 1
    cache.get_or_compute.assert_not_called()
