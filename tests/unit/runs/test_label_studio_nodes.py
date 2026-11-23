from collections.abc import Mapping
from datetime import UTC, datetime
from io import BytesIO
from json import loads
from typing import Any, cast
from uuid import UUID, uuid4
from xml.etree.ElementTree import fromstring

import httpx
import pytest
from grafy_core.contracts.ocr import TextRegion, TiffPage
from grafy_core.documents import TiffFile
from grafy_core.egress import (
    EgressPolicy,
    EgressRejectedError,
    PinnedPublicAddressTransport,
)
from grafy_core.node_context import (
    NodeExecutionContext,
    UserFacingNodeError,
    bind_node_secrets,
)
from grafy_core.node_ports import Ref
from grafy_core.plugins import NodeSecretInput
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.table_contracts import Table, TableColumn, TableValue
from grafy_plugin_map_toponyms.label_studio import (
    ExportLabelStudioConfig,
    ExportLabelStudioInput,
    ExportLabelStudioNode,
    ExportMode,
    ImportLabelStudioConfig,
    ImportLabelStudioInput,
    ImportLabelStudioNode,
    _sign_s3_put,  # pyright: ignore[reportPrivateUsage]
)
from grafy_plugin_map_toponyms.text_regions import TiffPixelWindow, TiffTextRegions
from PIL import Image
from pydantic import AnyHttpUrl, SecretStr

_CROPS = "Region crops (fast triage)"
_TILES = "Tiled windows (polygons)"
_HASH = "a" * 64
_TOKEN = "legacy-token"
_JWT = "header.payload.signature"


class _Credentials(UnavailableNodeSecretResolver):
    def __init__(self, token: str) -> None:
        self.token = token

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, object],
        actor_user_id: UUID | None = None,
    ) -> SecretStr:
        return SecretStr(
            {"label_studio_token": self.token, "s3_secret_key": "example-secret"}[name]
        )


class _Sheet:
    def __init__(self, token: str = _TOKEN) -> None:
        self.context = bind_node_secrets(
            NodeExecutionContext(workspace_id=uuid4()),
            _Credentials(token),
            (
                NodeSecretInput(
                    name="label_studio_token", title="Label Studio API token"
                ),
                NodeSecretInput(
                    name="s3_secret_key", title="MinIO / S3 secret access key"
                ),
            ),
        )
        self.source = Ref[TiffFile](
            artifact_id=uuid4(), artifact_type="file.tiff", schema_version=1
        )
        self.reads: list[tuple[int, int, int, int]] = []
        self.regions = [
            TextRegion(polygon=[(282.1, 263.2), (299.3, 267.4), (296.5, 290.6)]),
            TextRegion(polygon=[(331, 266), (354, 267), (350, 287)]),
        ]

    async def open(
        self, workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        assert workspace_id == self.context.workspace_id
        assert artifact_id == self.source.artifact_id
        return TiffPage(1500, 1400, self.read, source_sha256=_HASH, page=page)

    async def read(self, *, col: int, row: int, width: int, height: int) -> bytes:
        assert col + width <= 1500
        assert row + height <= 1400
        assert width * height <= 1_000_000
        self.reads.append((col, row, width, height))
        with Image.new("RGB", (width, height), (col % 255, row % 255, 100)) as image:
            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()

    def detected(self) -> TiffTextRegions:
        return TiffTextRegions(
            source=self.source, window=TiffPixelWindow(page=2), regions=self.regions
        )


class _Studio:
    def __init__(self, token: str = _TOKEN) -> None:
        self.token = token
        self.refreshes = 0
        self.projects: list[dict[str, Any]] = [{"id": 1, "title": "Other Project"}]
        self.tasks: list[dict[str, Any]] = []
        self.uploads: dict[str, tuple[int, int]] = {}
        self.upload_bytes: dict[str, bytes] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            assert request.url.host == "s3.example"
            assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
            assert request.headers["content-type"] == "image/png"
            assert request.headers["host"] == "s3.example:9100"
            assert request.url.path.endswith(".png")
            with Image.open(BytesIO(request.content)) as image:
                assert image.format == "PNG"
                self.uploads[request.url.path] = image.size
            self.upload_bytes[request.url.path] = request.content
            return httpx.Response(200)

        assert request.url.host == "studio.example"
        path = request.url.path
        if path == "/api/token/refresh/":
            assert request.method == "POST"
            assert "authorization" not in request.headers
            assert loads(request.content) == {"refresh": _JWT}
            self.refreshes += 1
            return httpx.Response(200, json={"access": "access-token"})

        assert request.headers["authorization"] == (
            "Bearer access-token" if self.token == _JWT else f"Token {self.token}"
        )
        if path == "/api/projects/" and request.method == "GET":
            assert request.url.params["page_size"] == "100"
            page = int(request.url.params["page"])
            return httpx.Response(
                200,
                json={
                    "count": len(self.projects),
                    # The server-provided URL must not become the request destination.
                    "next": "https://untrusted.example"
                    if page < len(self.projects)
                    else None,
                    "results": self.projects[page - 1 : page],
                },
            )
        if path == "/api/projects/" and request.method == "POST":
            body = cast(dict[str, Any], loads(request.content))
            self.projects.append({"id": 7, **body})
            return httpx.Response(201, json=self.projects[-1])
        if path == "/api/tasks/":
            assert request.url.params["project"] == "7"
            assert request.url.params["fields"] == "all"
            page = int(request.url.params["page"])
            return httpx.Response(
                200,
                json={"total": len(self.tasks), "tasks": self.tasks[page - 1 : page]},
            )
        if path == "/api/projects/7/import":
            assert request.method == "POST"
            assert request.url.params["return_task_ids"] == "true"
            (task,) = cast(list[dict[str, Any]], loads(request.content))
            path = httpx.URL(task["data"]["image"]).path
            assert path in self.uploads
            self.tasks.append({"id": len(self.tasks) + 20, **task})
            return httpx.Response(201, json={"task_ids": [self.tasks[-1]["id"]]})
        raise AssertionError(f"Unexpected {request.method} {path}")


def _export_config(mode: ExportMode, **overrides: Any) -> ExportLabelStudioConfig:
    return ExportLabelStudioConfig.model_validate(
        {
            "label_studio_url": "https://studio.example",
            "s3_endpoint_url": "https://s3.example:9100",
            "s3_public_url": "https://images.example",
            "s3_prefix": "grafy/map tiles",
            "mode": mode,
            "tile_edge_px": 256,
            **overrides,
        }
    )


def _import_config(**overrides: Any) -> ImportLabelStudioConfig:
    return ImportLabelStudioConfig.model_validate(
        {
            "label_studio_url": "https://studio.example",
            "page": 2,
            **overrides,
        }
    )


def _scores(*entries: tuple[int, str, float]) -> Table:
    rows: list[dict[str, TableValue]] = [
        {
            "region_index": index,
            "p_text": 0.87,
            "predicted_kind": "other_text",
            "triage_band": band,
            "uncertainty": uncertainty,
            "p_settlement": 0.16,
            "p_other_text": 0.71,
            "p_trees": 0.05,
            "p_other_symbol": 0.08,
        }
        for index, band, uncertainty in entries
    ]
    return Table(columns=[TableColumn(id=key, title=key) for key in rows[0]], rows=rows)


def test_s3_put_signature_matches_aws_sdk_vector() -> None:
    headers = _sign_s3_put(
        httpx.URL("https://s3.example:9100/tiles/a%20b/%C5%BC.png"),
        b"test image",
        access_key="AKIDEXAMPLE",
        secret_key=SecretStr("example-secret"),
        region="us-east-1",
        now=datetime(2026, 1, 1, 1, 2, 3, tzinfo=UTC),
    )
    assert headers == {
        "content-type": "image/png",
        "host": "s3.example:9100",
        "x-amz-date": "20260101T010203Z",
        "x-amz-content-sha256": "1187327c6d0f0b0b19b33ab211a549023aa9a41f359c6d0a827d7bd99f8d5994",
        "authorization": (
            "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20260101/us-east-1/s3/aws4_request, "
            "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, "
            "Signature=2edfccbcff67aa2a67de26b915a3d98e04c6626f882336d76be85c919d482677"
        ),
    }


@pytest.mark.parametrize(
    "mode,scored", [(_CROPS, True), (_CROPS, False), (_TILES, True), (_TILES, False)]
)
async def test_export_modes_and_reexport(mode: ExportMode, scored: bool) -> None:
    token = _JWT if scored else _TOKEN
    sheet = _Sheet(token)
    studio = _Studio(token)
    config = _export_config(mode)
    scores = _scores((0, "prelabel", 0.9), (1, "review", 0.2)) if scored else None
    inputs = ExportLabelStudioInput(regions=sheet.detected(), scores=scores)
    async with httpx.AsyncClient(transport=httpx.MockTransport(studio)) as client:
        node = ExportLabelStudioNode(sheet.open, client=client)
        first = await node.run(sheet.context, config, inputs)
        reads = list(sheet.reads)
        second = await node.run(sheet.context, config, inputs)
    assert sheet.reads == reads
    assert len(studio.projects) == 2
    assert studio.refreshes == (2 if scored else 0)
    assert len(studio.tasks) == len(studio.uploads) == (2 if mode == _CROPS else 1)
    assert first.summary.rows == [
        {**row, "status": "exported"} for row in second.summary.rows
    ]
    assert all(row["status"] == "skipped_existing" for row in second.summary.rows)

    xml = fromstring(studio.projects[-1]["label_config"])
    assert xml.find("Image") is not None
    first_task = studio.tasks[0]
    data = first_task["data"]
    assert (data["source_sha256"], data["mode"], data["page"]) == (_HASH, mode, 2)
    assert (
        data["image"]
        == f"https://images.example/label-studio/grafy/map%20tiles/{data['grafy_key']}.png"
    )
    upload_path = httpx.URL(data["image"]).path
    with Image.open(BytesIO(studio.upload_bytes[upload_path])) as uploaded_image:
        raw_rgb = uploaded_image.convert("RGB").tobytes()
    pixels = {
        (raw_rgb[i], raw_rgb[i + 1], raw_rgb[i + 2]) for i in range(0, len(raw_rgb), 3)
    }
    if mode == _CROPS:
        assert (255, 0, 255) in pixels
        assert xml.find("Header") is not None
        assert [
            choice.attrib["hotkey"] for choice in xml.findall("./Choices/Choice")
        ] == ["1", "2", "3", "4"]
        polygon = sheet.regions[1 if scored else 0].model_dump(mode="json")["polygon"]
        assert data["polygon"] == polygon
        assert (data["tile_width"], data["tile_height"]) == (280, 280)
        assert data["triage_summary"].startswith("review" if scored else "Unscored")
        if scored:
            assert (
                data["triage_band"],
                data["predicted_kind"],
                data["p_text"],
                data["uncertainty"],
            ) == ("review", "other_text", 0.87, 0.2)
    else:
        assert (255, 0, 255) not in pixels
        assert (
            len(
                {
                    label.attrib["background"]
                    for label in xml.findall("./PolygonLabels/Label")
                }
            )
            == 4
        )
        assert "polygon" not in data
        assert (
            data["tile_col"],
            data["tile_row"],
            data["tile_width"],
            data["tile_height"],
        ) == (256, 256, 256, 256)
    if scored:
        prediction = first_task["predictions"][0]
        assert prediction["model_version"] == "jev-1.14.0"
        assert prediction["score"] == 0.71
        results = prediction["result"]
        assert results[0]["score"] == 0.71
        if mode == _CROPS:
            assert results[0]["value"] == {"choices": ["other_text"]}
        else:
            assert results[0]["value"] == {
                "polygonlabels": ["other_text"],
                "points": [
                    [75 * 100 / 256, 10 * 100 / 256],
                    [98 * 100 / 256, 11 * 100 / 256],
                    [94 * 100 / 256, 31 * 100 / 256],
                ],
            }
            assert len(results) == 2
    elif mode == _CROPS:
        assert "predictions" not in first_task
    else:
        prediction = first_task["predictions"][0]
        assert prediction["model_version"] == "craft"
        assert prediction["score"] == 0.5
        results = prediction["result"]
        assert len(results) == 2
        assert results[0]["value"]["polygonlabels"] == ["other_text"]
        assert len(data["jev_polygons"]) == 2


async def test_crop_priority_skips_auto_drop_and_caps_new_uploads() -> None:
    sheet = _Sheet()
    sheet.regions += [
        TextRegion(polygon=[(14, 17), (21, 17), (21, 25)]),
        TextRegion(polygon=[(14, 27), (21, 27), (21, 35)]),
    ]
    studio = _Studio()
    inputs = ExportLabelStudioInput(
        regions=sheet.detected(),
        scores=_scores(
            (0, "prelabel", 0.99),
            (1, "review", 0.1),
            (2, "review", 0.4),
            (3, "auto_drop", 0.91),
        ),
    )
    config = _export_config(_CROPS, max_tasks=2, skip_auto_drop=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(studio)) as client:
        node = ExportLabelStudioNode(sheet.open, client=client)
        first = await node.run(sheet.context, config, inputs)
        second = await node.run(sheet.context, config, inputs)
    assert [(row["status"], row["uncertainty"]) for row in first.summary.rows] == [
        ("exported", 0.4),
        ("exported", 0.1),
        ("skipped_auto_drop", 0.91),
    ]
    assert [(row["status"], row["triage_band"]) for row in second.summary.rows] == [
        ("skipped_existing", "review"),
        ("skipped_existing", "review"),
        ("exported", "prelabel"),
        ("skipped_auto_drop", "auto_drop"),
    ]


async def test_export_retries_after_label_studio_committed_the_task() -> None:
    sheet = _Sheet()
    sheet.regions = sheet.regions[:1]
    studio = _Studio()

    def lose_import_reply(request: httpx.Request) -> httpx.Response:
        response = studio(request)
        if request.url.path == "/api/projects/7/import":
            raise httpx.ReadTimeout("Lost response after the task was created")
        return response

    inputs = ExportLabelStudioInput(
        regions=sheet.detected(), scores=_scores((0, "review", 0.4))
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lose_import_reply)
    ) as client:
        node = ExportLabelStudioNode(sheet.open, client=client)
        with pytest.raises(UserFacingNodeError, match="Could not reach Label Studio"):
            await node.run(sheet.context, _export_config(_CROPS), inputs)
        result = await node.run(sheet.context, _export_config(_CROPS), inputs)
    assert len(sheet.reads) == len(studio.tasks) == 1
    assert studio.tasks[0]["predictions"][0]["score"] == 0.71
    assert result.summary.rows[0]["task_id"] == 20
    assert result.summary.rows[0]["status"] == "skipped_existing"


async def test_large_tile_uses_bounded_native_tiff_reads() -> None:
    sheet = _Sheet()
    studio = _Studio()
    async with httpx.AsyncClient(transport=httpx.MockTransport(studio)) as client:
        await ExportLabelStudioNode(sheet.open, client=client).run(
            sheet.context,
            _export_config(_TILES, tile_edge_px=2048),
            ExportLabelStudioInput(regions=sheet.detected()),
        )
    assert list(studio.uploads.values()) == [(1500, 1400)]
    assert sheet.reads == [
        (0, 0, 1000, 1000),
        (1000, 0, 500, 1000),
        (0, 1000, 1000, 400),
        (1000, 1000, 500, 400),
    ]


@pytest.mark.parametrize("mode", [_CROPS, _TILES])
async def test_annotations_round_trip_exact_source_pixels(mode: ExportMode) -> None:
    sheet = _Sheet()
    studio = _Studio()
    inputs = ExportLabelStudioInput(
        regions=sheet.detected(),
        scores=_scores((0, "review", 0.9), (1, "review", 0.4)),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(studio)) as client:
        exporter = ExportLabelStudioNode(sheet.open, client=client)
        importer = ImportLabelStudioNode(sheet.open, client=client)
        await exporter.run(
            sheet.context, _export_config(mode, tile_edge_px=277), inputs
        )
        original = list(studio.tasks)
        for task in original:
            results = task["predictions"][0]["result"]
            task["annotations"] = [
                {"id": 89, "updated_at": "2026-01-01T12:00:00Z", "result": results},
                {
                    "id": 90,
                    "updated_at": "2026-02-11T12:00:00Z",
                    "was_cancelled": True,
                    "result": [],
                },
                {"id": 88, "updated_at": "2025-12-01T12:00:00Z", "result": []},
            ]
        studio.tasks = [
            {**original[0], "id": 99, "data": {**original[0]["data"], "page": 1}},
            {
                **original[0],
                "id": 98,
                "data": {**original[0]["data"], "source_sha256": "b" * 64},
            },
            *original,
        ]
        restored = await importer.run(
            sheet.context, _import_config(), ImportLabelStudioInput(source=sheet.source)
        )
    assert restored.regions == TiffTextRegions(
        source=sheet.source,
        window=TiffPixelWindow(page=2, col=282, row=263, width=72, height=28),
        regions=sheet.regions,
    )
    assert [row["task_id"] for row in restored.annotations.rows] == [20, 21]
    assert [row["human_label"] for row in restored.annotations.rows] == [
        "other_text",
        "other_text",
    ]
    assert restored.annotations.rows[0]["x"] == 282.1
    assert restored.annotations.rows[0]["y"] == 263.2
    assert all(row["from_annotation"] is True for row in restored.annotations.rows)
    assert all(
        row["updated_at"] == "2026-01-01T12:00:00+00:00"
        for row in restored.annotations.rows
    )


async def test_import_prediction_fallback_and_rectangle_labels() -> None:
    sheet = _Sheet()
    studio = _Studio()
    studio.tasks.append(
        {
            "id": 20,
            "data": {
                "source_sha256": _HASH,
                "page": 2,
                "grafy_key": "fixture",
                "tile_col": 10,
                "tile_row": 20,
                "tile_width": 80,
                "tile_height": 60,
            },
            "predictions": [
                {
                    "id": 1,
                    "created_at": "2026-01-01T12:00:00Z",
                    "result": [
                        {
                            "type": "rectanglelabels",
                            "value": {
                                "x": 25,
                                "y": 50,
                                "width": 50,
                                "height": 25,
                                "rectanglelabels": ["text"],
                            },
                        },
                        {
                            "type": "choices",
                            "value": {"choices": ["trees_or_vegetation"]},
                        },
                    ],
                }
            ],
        }
    )
    inputs = ImportLabelStudioInput(source=sheet.source)
    async with httpx.AsyncClient(transport=httpx.MockTransport(studio)) as client:
        node = ImportLabelStudioNode(sheet.open, client=client)
        empty = await node.run(sheet.context, _import_config(project_id=7), inputs)
        result = await node.run(
            sheet.context, _import_config(project_id=7, only_annotated=False), inputs
        )
    assert empty.regions.window == TiffPixelWindow(page=2, width=1, height=1)
    assert not empty.annotations.rows
    assert result.regions.regions[0].polygon == [(30, 50), (70, 50), (70, 65), (30, 65)]
    assert result.annotations.rows == [
        {
            "task_id": 20,
            "grafy_key": "fixture",
            "human_label": "text",
            "page": 2,
            "x": 30,
            "y": 50,
            "width": 40,
            "height": 15,
            "from_annotation": False,
            "updated_at": "2026-01-01T12:00:00+00:00",
        }
    ]


async def test_pinned_egress_rejects_ungranted_private_label_studio() -> None:
    sheet = _Sheet()

    def no_dial(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected request to {request.url}")

    transport = PinnedPublicAddressTransport(
        policy=EgressPolicy(), transport=httpx.MockTransport(no_dial)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        importer = ImportLabelStudioNode(sheet.open, client=client)
        with pytest.raises(
            UserFacingNodeError, match="Label Studio may not be dialed"
        ) as error:
            await importer.run(
                sheet.context,
                ImportLabelStudioConfig(
                    label_studio_url=AnyHttpUrl("http://127.0.0.1:8085")
                ),
                ImportLabelStudioInput(source=sheet.source),
            )
    assert isinstance(error.value.__cause__, EgressRejectedError)


async def test_pinned_egress_checks_s3_separately() -> None:
    sheet = _Sheet()
    studio = _Studio()

    def label_studio_only(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == "127.0.0.1:8085"
        fixture_request = httpx.Request(
            request.method,
            request.url.copy_with(host="studio.example"),
            headers=request.headers,
            content=request.content,
        )
        return studio(fixture_request)

    transport = PinnedPublicAddressTransport(
        policy=EgressPolicy.from_destinations(["127.0.0.1:8085"]),
        transport=httpx.MockTransport(label_studio_only),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        exporter = ExportLabelStudioNode(sheet.open, client=client)
        with pytest.raises(
            UserFacingNodeError, match="MinIO / S3 may not be dialed"
        ) as error:
            await exporter.run(
                sheet.context,
                ExportLabelStudioConfig(),
                ExportLabelStudioInput(regions=sheet.detected()),
            )
    assert isinstance(error.value.__cause__, EgressRejectedError)
    assert not studio.tasks
