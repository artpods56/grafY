from base64 import b64decode
from collections.abc import Sequence
from io import BytesIO
import json
from uuid import uuid4

import httpx
import pytest
from PIL import Image, ImageDraw
from pydantic import SecretStr

from grafy_core.artifacts import NoConfig
from grafy_core.documents import TiffFile
from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.node_ports import Ref
from grafy_core.provider_cache import InMemoryCacheStore, ProviderCache
from grafy_core.text_regions import TextReading, TextRecognizer, TextRegion, TiffPage
from grafy_workbench.ocr.paddle_recognizer import (
    PADDLE_MODEL,
    PADDLE_URL,
    PaddleCyrillicRecognizer,
)
from grafy_workbench.ocr.provider_http import serve_client
from grafy_workbench.ocr.tiff_recognition import ReadTiffTextNode, RecognizeInput
from grafy_workbench.ocr.text_regions import TiffPixelWindow, TiffTextRegions


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
    assert context.output_metadata["tiff_cache_hits"] == 0
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

    async def run() -> NodeExecutionContext:
        context = NodeExecutionContext(workspace_id=workspace_id)
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
    second = await run()

    assert batches == [2]
    assert second.output_metadata["tiff_cache_hits"] == 2


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
