import asyncio
from base64 import b64decode
from collections.abc import Mapping
from dataclasses import replace
from io import BytesIO
from json import loads
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from grafy_core.contracts.ocr import TextRegion, TiffPage
from grafy_core.documents import TiffFile
from grafy_core.node_context import (
    NodeExecutionContext,
    UserFacingNodeError,
    bind_node_secrets,
)
from grafy_core.node_ports import Ref
from grafy_core.plugins import NodeSecretInput
from grafy_core.provider_cache import InMemoryCacheStore, ProviderCache
from grafy_plugin_map_toponyms.jev_filter import (
    FilterTiffJevConfig,
    FilterTiffJevInput,
    FilterTiffJevNode,
)
from grafy_core.provider_http import ProviderRequest, post_json, serve_client
from grafy_plugin_map_toponyms.text_regions import TiffPixelWindow, TiffTextRegions
from PIL import Image
from pydantic import JsonValue, SecretStr


class _Secrets:
    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
        actor_user_id: UUID | None = None,
    ) -> SecretStr:
        assert name == "api_key"
        return SecretStr("test-key")

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        return "test-revision"


class _Sheet:
    def __init__(
        self, *regions: TextRegion, width: int = 1000, height: int = 900
    ) -> None:
        self.calls: list[tuple[int, int, int, int]] = []
        self.width = width
        self.height = height
        self.context = bind_node_secrets(
            NodeExecutionContext(workspace_id=uuid4()),
            _Secrets(),
            (NodeSecretInput(name="api_key", title="Jev API key"),),
        )
        self.inputs = FilterTiffJevInput(
            regions=TiffTextRegions(
                source=Ref[TiffFile](
                    artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
                ),
                window=TiffPixelWindow(
                    page=2, col=4, row=9, width=width - 4, height=height - 9
                ),
                regions=list(regions),
            ),
        )

    async def _read(self, *, col: int, row: int, width: int, height: int) -> bytes:
        self.calls.append((col, row, width, height))
        assert 0 <= col < col + width <= self.width
        assert 0 <= row < row + height <= self.height
        png = BytesIO()
        with Image.new("L", (width, height), 200) as image:
            image.save(png, format="PNG")
        return png.getvalue()

    async def open_page(
        self, workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        assert workspace_id == self.context.workspace_id
        assert artifact_id == self.inputs.regions.source.artifact_id
        assert page == 2
        return TiffPage(
            self.width, self.height, self._read, source_sha256="a" * 64, page=page
        )


def _region(x: float, y: float, width: float = 30, height: float = 20) -> TextRegion:
    return TextRegion(
        polygon=[(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    )


_KINDS = (
    "settlement_or_place_name",
    "other_text",
    "trees_or_vegetation",
    "other_symbol_or_artifact",
)


def _reply(
    scores: tuple[float, float, float, float] = (0.75, 0.1875, 0.03125, 0.03125),
    *,
    noul: JsonValue = 0.81,
) -> httpx.Response:
    probabilities = dict(zip(_KINDS, scores, strict=True))
    choice = max(_KINDS, key=probabilities.__getitem__)
    return httpx.Response(
        200,
        json={
            "model": "jev-1.14.0",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "answers": {
                "is_text": {"type": "noul", "noul": noul},
                "kind": {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": probabilities,
                    "confidence": 0.80,
                },
            },
        },
    )


@pytest.mark.parametrize(
    ("region", "window", "local_x", "local_y"),
    [
        (_region(400, 350, 150), (320, 220, 311, 280), 80, 130),
        (_region(3, 4), (0, 0, 280, 280), 3, 4),
        (_region(950, 860), (720, 620, 280, 280), 230, 240),
    ],
)
async def test_jev_sends_native_context_with_a_two_pixel_magenta_outline(
    region: TextRegion, window: tuple[int, int, int, int], local_x: int, local_y: int
) -> None:
    sheet = _Sheet(region)

    def jev(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"

        payload = cast("dict[str, object]", loads(request.content))
        assert payload["model"] == "jev-1.14.0"
        state = cast("dict[str, str]", payload["state"])
        assets = cast("dict[str, dict[str, str]]", payload["assets"])
        assert set(assets) == {state["map_image"]}
        asset = assets[state["map_image"]]
        assert asset["type"] == "image"
        assert asset["format"] == "png"
        questions = cast("dict[str, dict[str, object]]", payload["questions"])
        assert set(questions) == {"is_text", "kind"}
        assert questions["is_text"]["type"] == "noul"
        assert questions["kind"]["type"] == "choice"
        criteria = cast("dict[str, str]", questions["kind"]["criteria"])
        assert set(criteria) == set(_KINDS)

        with Image.open(BytesIO(b64decode(asset["data_base64"]))) as crop:
            assert (crop.format, crop.mode, crop.size) == ("PNG", "RGB", window[2:])
            assert crop.getpixel((local_x + 10, local_y)) == (255, 0, 255)
            assert crop.getpixel((local_x + 10, local_y + 1)) == (255, 0, 255)
            assert crop.getpixel((local_x + 10, local_y + 2)) == (200, 200, 200)
            assert crop.getpixel((local_x, local_y + 10)) == (255, 0, 255)
            assert crop.getpixel((0, 0)) == (200, 200, 200)
        return _reply()

    async with httpx.AsyncClient(transport=httpx.MockTransport(jev)) as client:
        with serve_client(client):
            result = await FilterTiffJevNode(sheet.open_page).run(
                sheet.context, FilterTiffJevConfig(), sheet.inputs
            )
    assert sheet.calls == [window]
    assert result.regions == sheet.inputs.regions


async def test_jev_reuses_scores_when_filtering_by_scope_and_threshold() -> None:
    settlement, text, tree = (
        _region(300, 350),
        _region(440, 350, 45),
        _region(600, 350, 60),
    )
    sheet = _Sheet(settlement, text, tree)
    node = FilterTiffJevNode(sheet.open_page, cache=ProviderCache(InMemoryCacheStore()))
    calls = 0
    replies = iter(
        (_reply(), _reply((0.125, 0.375, 0.25, 0.25)), _reply((0.05, 0.05, 0.80, 0.10)))
    )

    def jev(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return next(replies)

    async with httpx.AsyncClient(transport=httpx.MockTransport(jev)) as client:
        with serve_client(client):
            all_text = await node.run(
                sheet.context,
                FilterTiffJevConfig(max_concurrency=1, min_text_probability=0.50),
                sheet.inputs,
            )
            settlements = await node.run(
                sheet.context,
                FilterTiffJevConfig(keep_scope="Settlements only"),
                sheet.inputs,
            )
            high_threshold = await node.run(
                sheet.context,
                FilterTiffJevConfig(min_text_probability=0.95),
                sheet.inputs,
            )

    assert calls == 3
    assert all_text.regions.regions == [settlement, text]
    assert settlements.regions.regions == [settlement]
    assert high_threshold.regions.regions == []
    assert [(column.id, column.value_type) for column in all_text.scores.columns] == [
        ("region_index", "integer"),
        ("page", "integer"),
        ("x", "number"),
        ("y", "number"),
        ("width", "number"),
        ("height", "number"),
        ("p_text", "number"),
        ("p_is_text", "number"),
        ("p_settlement", "number"),
        ("p_other_text", "number"),
        ("p_trees", "number"),
        ("p_other_symbol", "number"),
        ("predicted_kind", "text"),
        ("triage_band", "text"),
        ("uncertainty", "number"),
        ("kept", "boolean"),
    ]
    assert [row["triage_band"] for row in all_text.scores.rows] == [
        "prelabel",
        "review",
        "auto_drop",
    ]
    assert [row["kept"] for row in settlements.scores.rows] == [True, False, False]
    assert all_text.scores.rows[0] == {
        "region_index": 0,
        "page": 2,
        "x": 300.0,
        "y": 350.0,
        "width": 30.0,
        "height": 20.0,
        "p_text": 0.9375,
        "p_is_text": 0.81,
        "p_settlement": 0.75,
        "p_other_text": 0.1875,
        "p_trees": 0.03125,
        "p_other_symbol": 0.03125,
        "predicted_kind": "settlement_or_place_name",
        "triage_band": "prelabel",
        "uncertainty": 0.125,
        "kept": True,
    }


async def test_jev_bounds_requests_and_reports_progress() -> None:
    sheet = _Sheet(_region(100, 100), _region(300, 300), _region(500, 500))
    release = asyncio.Event()
    progress: list[tuple[int | None, int | None]] = []
    active = 0
    peak = 0

    class Reporter:
        async def report_progress(
            self,
            context: NodeExecutionContext,
            message: str,
            *,
            current: int | None = None,
            total: int | None = None,
        ) -> None:
            progress.append((current, total))

    async def jev(_request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        assert active <= 2
        if active == 2:
            release.set()
        try:
            await release.wait()
            return _reply()
        finally:
            active -= 1

    context = replace(sheet.context, progress_reporter=Reporter())
    async with httpx.AsyncClient(transport=httpx.MockTransport(jev)) as client:
        with serve_client(client):
            result = await FilterTiffJevNode(sheet.open_page).run(
                context, FilterTiffJevConfig(max_concurrency=2), sheet.inputs
            )

    assert peak == 2
    assert result.regions == sheet.inputs.regions
    assert progress == [(0, 3), (1, 3), (2, 3), (3, 3)]


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, text="test-key"), "Visual Jev returned HTTP 401"),
        (_reply(noul="test-key"), "Visual Jev returned invalid region scores"),
        (_reply(noul=True), "Visual Jev returned invalid region scores"),
        (_reply((1.01, 0.0, 0.0, 0.0)), "Visual Jev returned invalid region scores"),
        (
            _reply((0.50, 0.25, 0.25, -0.01)),
            "Visual Jev returned invalid region scores",
        ),
    ],
)
async def test_jev_surfaces_safe_provider_errors(
    response: httpx.Response, message: str
) -> None:
    sheet = _Sheet(_region(200, 300))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: response)
    ) as client:
        with serve_client(client), pytest.raises(UserFacingNodeError) as error:
            await FilterTiffJevNode(sheet.open_page).run(
                sheet.context, FilterTiffJevConfig(max_retries=0), sheet.inputs
            )
    assert str(error.value) == message


async def test_provider_http_retries_529_and_protects_bearer_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter((529, 200))

    async def skip_backoff(_delay: float) -> None:
        pass

    def provider(request: httpx.Request) -> httpx.Response:
        assert request.headers.get_list("Authorization") == ["Bearer real-key"]
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        return httpx.Response(next(statuses), content=b"{}")

    monkeypatch.setattr("grafy_core.provider_http.sleep", skip_backoff)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with serve_client(client):
            result = await post_json(
                ProviderRequest(
                    service="Visual Jev",
                    url="https://api.typesafe.ai/v1/systemone",
                    payload={},
                    api_key=SecretStr("real-key"),
                    attempts=2,
                    timeout_seconds=1.0,
                    max_response_bytes=64,
                    extra_headers=(
                        ("authorization", "Bearer shadow-key"),
                        ("TypeSafe-Danger-Zone-Images", "true"),
                    ),
                )
            )
    assert result == b"{}"
    assert next(statuses, None) is None
