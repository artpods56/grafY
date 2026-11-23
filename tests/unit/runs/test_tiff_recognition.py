from grafy_core.text_regions import ServiceCacheIdentity
from base64 import b64decode
from collections.abc import Sequence
from io import BytesIO
import json
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image, ImageDraw
from pydantic import SecretStr

from grafy_core.artifacts import NoConfig
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.node_ports import Ref
from grafy_core.provider_cache import InMemoryCacheStore, ProviderCache
from grafy_core.text_regions import (
    PixelPoint,
    TextReading,
    TextRecognizer,
    TextRegion,
    TiffPage,
)
from grafy_workbench.ocr.paddle_recognizer import (
    PADDLE_MODEL,
    PADDLE_URL,
    PaddleCyrillicRecognizer,
)
from grafy_workbench.ocr.provider_http import serve_client
from grafy_workbench.ocr.tiff_label_crop import NATIVE_CROP_PIXEL_LIMIT
from grafy_workbench.ocr.tiff_recognition import (
    ReadTiffTextNode,
    RecognizeInput,
    RecognizeOutput,
)
from grafy_workbench.ocr.text_regions import TiffPixelWindow, TiffTextRegions


class ReadProgress:
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


async def test_reads_rotated_polygons_without_losing_their_source_coordinates():
    workspace_id, artifact_id = uuid4(), uuid4()
    polygon = [(10, 20), (86, 60), (80, 72), (4, 32)]
    scan = Image.new("RGB", (100, 100), "blue")
    ImageDraw.Draw(scan).polygon(polygon, fill="black")
    reads = []

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        reads.append((col, row, width, height))
        buf = BytesIO()
        scan.crop((col, row, col + width, row + height)).save(buf, format="PNG")
        return buf.getvalue()

    async def open_page(workspace: object, artifact: object, *, page: int) -> TiffPage:
        assert (workspace, artifact, page) == (workspace_id, artifact_id, 2)
        return TiffPage(100, 100, read, source_sha256="0" * 64, page=page)

    class Recognizer(TextRecognizer):
        def cache_identity(self):
            return ServiceCacheIdentity("test", "1")

        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            assert len(crops) == 1
            with Image.open(BytesIO(crops[0])) as crop:
                assert crop.width > crop.height * 2
                assert crop.getpixel((0, 0)) == (255, 255, 255)
                assert crop.getpixel((crop.width // 2, crop.height // 2)) == (0, 0, 0)
            return [TextReading(text="Бѣлыничи", confidence=0.81, model="test")]

    source = Ref[TiffFile](
        artifact_id=artifact_id, artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=2, col=0, row=0, width=100, height=100)
    regions = [
        TextRegion(polygon=polygon, score=0.62),
        TextRegion(polygon=[(5, 5), (6, 6), (7, 7)]),
    ]
    result = await ReadTiffTextNode(open_page).run(
        NodeExecutionContext(workspace_id=workspace_id),
        NoConfig(),
        RecognizeInput(
            regions=TiffTextRegions(source=source, window=window, regions=regions),
            recognizer=Recognizer(),
        ),
    )

    assert reads == [(0, 16, 90, 60)]
    assert result.text.source == source
    assert result.text.window == window
    assert [region.polygon for region in result.text.regions] == [
        region.polygon for region in regions
    ]
    assert result.text.regions[0].score == 0.62
    assert result.text.regions[0].reading == TextReading(
        text="Бѣлыничи", confidence=0.81, model="test"
    )
    assert result.text.regions[1].reading is None


async def test_a_repeated_crop_does_not_call_the_recognizer_again():
    workspace_id, artifact_id = uuid4(), uuid4()
    polygon = [(10, 20), (86, 60), (80, 72), (4, 32)]
    scan = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(scan).polygon(polygon, fill="black")
    calls = 0

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        buf = BytesIO()
        scan.crop((col, row, col + width, row + height)).save(buf, format="PNG")
        return buf.getvalue()

    async def open_page(workspace: object, artifact: object, *, page: int) -> TiffPage:
        del workspace, artifact
        return TiffPage(100, 100, read, source_sha256="ab" * 32, page=page)

    class Recognizer(TextRecognizer):
        def cache_identity(self):
            return ServiceCacheIdentity("test", "1")

        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            nonlocal calls
            calls += 1
            assert len(crops) == 1
            return [TextReading(text="same", confidence=0.9, model="test")]

    source = Ref[TiffFile](
        artifact_id=artifact_id, artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=0, col=0, row=0, width=100, height=100)
    region = TextRegion(polygon=polygon)
    context = NodeExecutionContext(workspace_id=workspace_id)
    result = await ReadTiffTextNode(
        open_page, cache=ProviderCache(InMemoryCacheStore())
    ).run(
        context,
        NoConfig(),
        RecognizeInput(
            regions=TiffTextRegions(
                source=source, window=window, regions=[region, region]
            ),
            recognizer=Recognizer(),
        ),
    )

    assert calls == 1
    assert context.output_metadata == {"tiff_crops": 2, "tiff_cache_hits": 0}
    assert [item.reading for item in result.text.regions] == [
        TextReading(text="same", confidence=0.9, model="test"),
        TextReading(text="same", confidence=0.9, model="test"),
    ]


async def test_distinct_misses_go_to_the_recognizer_in_one_call():
    workspace_id, artifact_id = uuid4(), uuid4()
    polygons = [
        [(10, 20), (86, 60), (80, 72), (4, 32)],
        [(8, 78), (70, 84), (66, 94), (4, 88)],
    ]
    scan = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(scan)
    for polygon in polygons:
        draw.polygon(polygon, fill="black")
    batches: list[int] = []

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        buf = BytesIO()
        scan.crop((col, row, col + width, row + height)).save(buf, format="PNG")
        return buf.getvalue()

    async def open_page(workspace: object, artifact: object, *, page: int) -> TiffPage:
        del workspace, artifact
        return TiffPage(100, 100, read, source_sha256="cd" * 32, page=page)

    class Recognizer(TextRecognizer):
        def cache_identity(self):
            return ServiceCacheIdentity("test", "1")

        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            batches.append(len(crops))
            return [
                TextReading(text="line", confidence=0.4, model="test") for _ in crops
            ]

    source = Ref[TiffFile](
        artifact_id=artifact_id, artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=0, col=0, row=0, width=100, height=100)
    regions = [TextRegion(polygon=polygon) for polygon in polygons]
    cache = ProviderCache(InMemoryCacheStore())
    node = ReadTiffTextNode(open_page, cache=cache)
    reporter = ReadProgress()

    async def run() -> NodeExecutionContext:
        context = NodeExecutionContext(
            workspace_id=workspace_id, node_id="read", progress_reporter=reporter
        )
        await node.run(
            context,
            NoConfig(),
            RecognizeInput(
                regions=TiffTextRegions(source=source, window=window, regions=regions),
                recognizer=Recognizer(),
            ),
        )
        return context

    await run()
    reporter.updates.clear()
    second = await run()

    assert batches == [2]
    assert second.output_metadata == {"tiff_crops": 2, "tiff_cache_hits": 2}
    assert reporter.updates == [
        ("Reading labels", 0, 2),
        ("Reading labels · 2 cached", 2, 2),
    ]


async def test_a_second_scan_of_the_same_labels_reads_the_cache_not_the_provider():
    workspace_id, artifact_id = uuid4(), uuid4()
    page_side = 400
    scan = Image.new("RGB", (page_side, page_side), "white")
    draw = ImageDraw.Draw(scan)
    regions: list[TextRegion] = []
    for index in range(8):
        # Each crop is cut tight, so these differ in width as well as in place.
        left, top = 12 + (index % 4) * 90, 12 + (index // 4) * 60
        right, bottom = left + 40 + 4 * index, top + 18
        draw.rectangle((left, top, right, bottom), fill="black")
        regions.append(
            TextRegion(
                polygon=[(left, top), (right, top), (right, bottom), (left, bottom)]
            )
        )
    batches: list[int] = []

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        buf = BytesIO()
        scan.crop((col, row, col + width, row + height)).save(buf, format="PNG")
        return buf.getvalue()

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        del workspace_id, artifact_id
        return TiffPage(page_side, page_side, read, source_sha256="ef" * 32, page=page)

    class Recognizer(TextRecognizer):
        def cache_identity(self):
            return ServiceCacheIdentity("test", "1")

        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            batches.append(len(crops))
            return [
                TextReading(text="line", confidence=0.4, model="test") for _ in crops
            ]

    source = Ref[TiffFile](
        artifact_id=artifact_id, artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=0, col=0, row=0, width=page_side, height=page_side)
    reporter = ReadProgress()
    context = NodeExecutionContext(
        workspace_id=workspace_id, node_id="read", progress_reporter=reporter
    )
    node = ReadTiffTextNode(open_page, cache=ProviderCache(InMemoryCacheStore()))

    await node.run(
        context,
        NoConfig(),
        RecognizeInput(
            regions=TiffTextRegions(source=source, window=window, regions=regions),
            recognizer=Recognizer(),
        ),
    )

    # One step of eight crops is one provider call, cache or no cache.
    assert batches == [8]
    assert context.output_metadata == {"tiff_crops": 8, "tiff_cache_hits": 0}
    assert reporter.updates == [("Reading labels", 0, 8), ("Reading labels", 8, 8)]

    reporter.updates.clear()
    await node.run(
        context,
        NoConfig(),
        RecognizeInput(
            regions=TiffTextRegions(source=source, window=window, regions=regions),
            recognizer=Recognizer(),
        ),
    )

    assert batches == [8]
    assert context.output_metadata == {"tiff_crops": 8, "tiff_cache_hits": 8}
    assert reporter.updates == [
        ("Reading labels", 0, 8),
        ("Reading labels · 8 cached", 8, 8),
    ]


async def test_the_paddle_route_is_asked_once_for_two_scans_of_one_label():
    # The provider node hands out a PaddleCyrillicRecognizer, and the crop node is
    # the only thing that ever calls it, so that one call site is the one cache.
    workspace_id = uuid4()
    polygon: list[PixelPoint] = [(10, 20), (86, 60), (80, 72), (4, 32)]
    scan = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(scan).polygon(polygon, fill="black")
    asked: list[int] = []

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        buf = BytesIO()
        scan.crop((col, row, col + width, row + height)).save(buf, format="PNG")
        return buf.getvalue()

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        del workspace_id, artifact_id
        return TiffPage(100, 100, read, source_sha256="11" * 32, page=page)

    def respond(request: httpx.Request) -> httpx.Response:
        crops = json.loads(request.content)["images_base64"]
        asked.append(len(crops))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"text": "Бѣлыничи", "confidence": 0.8, "model": PADDLE_MODEL}
                    for _ in crops
                ]
            },
        )

    source = Ref[TiffFile](
        artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=0, col=0, row=0, width=100, height=100)
    reporter = ReadProgress()
    second = NodeExecutionContext(
        workspace_id=workspace_id, node_id="read", progress_reporter=reporter
    )
    node = ReadTiffTextNode(open_page, cache=ProviderCache(InMemoryCacheStore()))

    async def read_labels(context: NodeExecutionContext) -> None:
        await node.run(
            context,
            NoConfig(),
            RecognizeInput(
                regions=TiffTextRegions(
                    source=source,
                    window=window,
                    regions=[TextRegion(polygon=polygon)],
                ),
                recognizer=PaddleCyrillicRecognizer(
                    SecretStr("scoped-test"), timeout_ms=30_000, max_retries=0
                ),
            ),
        )

    with serve_client(httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        await read_labels(NodeExecutionContext(workspace_id=workspace_id))
        reporter.updates.clear()
        await read_labels(second)

    assert asked == [1]
    assert second.output_metadata == {"tiff_crops": 1, "tiff_cache_hits": 1}
    assert reporter.updates == [
        ("Reading labels", 0, 1),
        ("Reading labels · 1 cached", 1, 1),
    ]


def _window_png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "black").save(buffer, format="PNG")
    return buffer.getvalue()


async def test_a_label_wider_than_one_native_read_is_stitched_from_several_reads():
    # The span a 12 box diagonal run joins into: a 1,280 x 1,280 box, 1,658,944 pixels
    # with its margin, which is more than the tiler serves in one window. It is read
    # in abutting strips and pasted back into one image, so the name is still read
    # once rather than split across the spans it was joined from.
    span = [
        (871.7157287525382, 843.4314575050761),
        (843.4314575050761, 871.7157287525382),
        (2094.2842712474617, 2122.568542494924),
        (2122.568542494924, 2094.2842712474617),
    ]
    reads: list[tuple[int, int, int, int]] = []

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        assert width * height <= NATIVE_CROP_PIXEL_LIMIT
        reads.append((col, row, width, height))
        return _window_png(width, height)

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        del workspace_id, artifact_id
        return TiffPage(4000, 5000, read, source_sha256="0" * 64, page=page)

    crops: list[bytes] = []

    class Recognizer(TextRecognizer):
        def cache_identity(self):
            return ServiceCacheIdentity("test", "1")

        async def recognize(self, requests: Sequence[bytes]) -> list[TextReading]:
            crops.extend(requests)
            return [
                TextReading(text="MI", confidence=0.9, model="test") for _ in requests
            ]

    source = Ref[TiffFile](
        artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=0, col=0, row=0, width=4000, height=5000)

    await ReadTiffTextNode(open_page).run(
        NodeExecutionContext(workspace_id=uuid4()),
        NoConfig(),
        RecognizeInput(
            regions=TiffTextRegions(
                source=source, window=window, regions=[TextRegion(polygon=span)]
            ),
            recognizer=Recognizer(),
        ),
    )

    # Two strips, each within one read, abutting with no gap and no overlap.
    assert reads == [(839, 839, 776, 1288), (1615, 839, 512, 1288)]
    assert sum(width for _, _, width, _ in reads) == 1288
    assert len(crops) == 1
    with Image.open(BytesIO(crops[0])) as crop:
        assert crop.width * crop.height <= NATIVE_CROP_PIXEL_LIMIT


@pytest.mark.parametrize("invalid_revision", [False, True])
async def test_paddle_passes_ordered_batches_to_the_scoped_route(
    invalid_revision: bool,
):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ocr/cyrillic/recognize"
        assert request.headers["Authorization"] == "Bearer scoped-test"
        crops = [
            b64decode(value).decode()
            for value in json.loads(request.content)["images_base64"]
        ]
        requests.append(crops)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "text": value,
                        "confidence": 0.8,
                        "model": "wrong" if invalid_revision else PADDLE_MODEL,
                    }
                    for value in crops
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = PaddleCyrillicRecognizer(
        SecretStr("scoped-test"), timeout_ms=30_000, max_retries=0
    )
    crops = [str(i) for i in range(9)]
    with serve_client(client):
        if invalid_revision:
            with pytest.raises(UserFacingNodeError, match="unexpected model revision"):
                await provider.recognize([crop.encode() for crop in crops])
            return
        result = await provider.recognize([crop.encode() for crop in crops])
    assert requests == [crops[:8], crops[8:]]
    assert [reading.text for reading in result] == crops


async def test_paddle_retries_a_batch_the_provider_never_answered():
    answers = iter(
        (
            httpx.ConnectError("connection refused"),
            httpx.Response(
                200,
                json={
                    "results": [
                        {"text": "да", "confidence": 0.7, "model": PADDLE_MODEL}
                    ]
                },
            ),
        )
    )
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    provider = PaddleCyrillicRecognizer(
        SecretStr("scoped-test"), timeout_ms=30_000, max_retries=1
    )
    with serve_client(httpx.AsyncClient(transport=httpx.MockTransport(respond))):
        readings = await provider.recognize([b"crop"])
    assert calls == 2
    assert [reading.text for reading in readings] == ["да"]


async def test_paddle_names_a_provider_that_stops_answering():
    def refuse(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout(
            "no response", request=httpx.Request("POST", PADDLE_URL)
        )

    provider = PaddleCyrillicRecognizer(
        SecretStr("scoped-test"), timeout_ms=30_000, max_retries=1
    )
    with (
        serve_client(httpx.AsyncClient(transport=httpx.MockTransport(refuse))),
        pytest.raises(UserFacingNodeError, match="Could not reach Cyrillic OCR"),
    ):
        await provider.recognize([b"crop"])


async def _run_identity_recognition(
    cache: ProviderCache, context: NodeExecutionContext, recognizer: TextRecognizer
) -> RecognizeOutput:
    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        return _window_png(width, height)

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        return TiffPage(100, 100, read, source_sha256="c" * 64, page=page)

    source = Ref[TiffFile](
        artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
    )
    regions = TiffTextRegions(
        source=source,
        window=TiffPixelWindow(page=0, col=0, row=0, width=100, height=100),
        regions=[TextRegion(polygon=[(10, 10), (60, 10), (60, 30), (10, 30)])],
    )
    return await ReadTiffTextNode(open_page, cache=cache).run(
        context, NoConfig(), RecognizeInput(regions=regions, recognizer=recognizer)
    )


async def test_recognizer_identities_isolate_cache_entries():
    class Recognizer(TextRecognizer):
        def __init__(self, deployment: str):
            self.deployment = deployment
            self.calls = 0

        def cache_identity(self) -> ServiceCacheIdentity:
            return ServiceCacheIdentity(self.deployment, "1")

        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            self.calls += 1
            return [TextReading(text=self.deployment, model="1") for _ in crops]

    cache = ProviderCache(InMemoryCacheStore())
    context = NodeExecutionContext(workspace_id=uuid4())
    first, second = Recognizer("first"), Recognizer("second")

    first_result = await _run_identity_recognition(cache, context, first)
    second_result = await _run_identity_recognition(cache, context, second)
    await _run_identity_recognition(cache, context, second)
    assert first_result.text.regions[0].reading is not None
    assert first_result.text.regions[0].reading.text == "first"
    assert second_result.text.regions[0].reading is not None
    assert second_result.text.regions[0].reading.text == "second"
    assert (first.calls, second.calls) == (1, 1)


async def test_recognizer_moving_revision_bypasses_cache():
    from unittest.mock import AsyncMock

    class Recognizer(TextRecognizer):
        def cache_identity(self) -> ServiceCacheIdentity:
            return ServiceCacheIdentity("moving", None)

        async def recognize(self, crops: Sequence[bytes]) -> list[TextReading]:
            return [TextReading(text="fresh", model="latest") for _ in crops]

    cache = ProviderCache(InMemoryCacheStore())
    cache.get_or_compute_many = AsyncMock(side_effect=AssertionError("cache accessed"))

    result = await _run_identity_recognition(
        cache, NodeExecutionContext(workspace_id=uuid4()), Recognizer()
    )
    assert result.text.regions[0].reading is not None
    assert result.text.regions[0].reading.text == "fresh"
    cache.get_or_compute_many.assert_not_called()
