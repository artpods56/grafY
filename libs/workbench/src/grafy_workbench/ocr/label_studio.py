"""Exchange source-page TIFF regions with Label Studio."""

from asyncio import AbstractEventLoop, Lock, get_running_loop
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from hmac import digest as hmac_digest
from io import BytesIO
from itertools import count
from json import dumps
from math import ceil, cos, floor, radians, sin
from typing import Annotated, Literal, final, override
from urllib.parse import quote
from weakref import WeakValueDictionary

import httpx
from PIL import Image, ImageDraw
from pydantic import (
    AliasChoices,
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    Field,
    JsonValue,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.documents import TiffFile
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.egress import EgressRejectedError, PinnedPublicAddressTransport
from grafy_core.node_context import UserFacingNodeError
from grafy_core.node_ports import Ref
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
)
from grafy_core.table_contracts import Table, TableColumn, TableValue, TableValueType
from grafy_core.text_regions import (
    PixelPoint,
    PixelPolygon,
    TextRegion,
    TiffPage,
    TiffPageOpener,
)
from grafy_workbench.ocr.declaration import OCR
from grafy_workbench.ocr.text_regions import TiffPixelWindow, TiffTextRegions
from grafy_workbench.ocr.tiff_scan import Window
from grafy_workbench.table import plugin as _table_plugin

_ = _table_plugin.__name__

_NATIVE_CROP_PIXEL_LIMIT = 1_000_000
_MAGENTA = "#ff00ff"

type ExportMode = Literal["Region crops (fast triage)", "Tiled windows (polygons)"]
_CROPS = "Region crops (fast triage)"
_TILES = "Tiled windows (polygons)"
_LABEL_COLORS = {
    "settlement_or_place_name": "#2563eb",
    "other_text": "#16a34a",
    "trees_or_vegetation": "#eab308",
    "other_symbol_or_artifact": "#dc2626",
}
_IMAGE_TAG = '<Image name="image" value="$image" zoom="true" />'
_LABEL_CONFIGS = {
    _CROPS: (
        f'<View>{_IMAGE_TAG}<Header value="$triage_summary" />'
        '<Choices name="kind" toName="image" choice="single" showInline="true">'
        + "".join(
            f'<Choice value="{label}" hotkey="{index}" />'
            for index, label in enumerate(_LABEL_COLORS, 1)
        )
        + "</Choices></View>"
    ),
    _TILES: (
        f'<View>{_IMAGE_TAG}<PolygonLabels name="label" toName="image">'
        + "".join(
            f'<Label value="{label}" background="{color}" />'
            for label, color in _LABEL_COLORS.items()
        )
        + "</PolygonLabels></View>"
    ),
}
_CAPABILITIES = (
    PluginRuntimeCapability.NETWORK_EGRESS,
    PluginRuntimeCapability.NODE_SECRETS,
)
_LS_TOKEN = NodeSecretInput(name="label_studio_token", title="Label Studio API token")
_S3_SECRET = NodeSecretInput(name="s3_secret_key", title="MinIO / S3 secret access key")
_ADVANCED: dict[str, JsonValue] = {"x-grafy-advanced": True}
_PROJECT_TITLE = "Grafy Map OCR Triage"
_PAGE_SIZE = 100
_PROJECT_LOCKS: WeakValueDictionary[tuple[AbstractEventLoop, str, str], Lock] = (
    WeakValueDictionary()
)


def _segments(value: str) -> list[str]:
    return [segment for segment in value.split("/") if segment]


class _LabelStudioConfig(NodeConfig):
    label_studio_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8085")
    project_title: str = _PROJECT_TITLE
    timeout_ms: int = Field(
        default=30_000, ge=1_000, le=300_000, json_schema_extra=_ADVANCED
    )

    @field_validator(
        "label_studio_url", "s3_endpoint_url", "s3_public_url", check_fields=False
    )
    @classmethod
    def _service_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if any(
            part is not None
            for part in (value.username, value.password, value.query, value.fragment)
        ):
            raise ValueError(
                "Service URLs must omit credentials, queries and fragments"
            )
        return value


class ExportLabelStudioConfig(_LabelStudioConfig):
    mode: ExportMode = _CROPS
    s3_endpoint_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:9100")
    s3_public_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:9100")
    s3_bucket: str = "label-studio"
    s3_prefix: str = "grafy-ocr"
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    max_tasks: int = Field(default=200, ge=1, le=2000)
    skip_auto_drop: bool = False
    context_padding_px: int = Field(
        default=80, ge=16, le=256, json_schema_extra=_ADVANCED
    )
    min_crop_edge_px: int = Field(
        default=280, ge=280, le=1000, json_schema_extra=_ADVANCED
    )
    tile_edge_px: int = Field(
        default=1000, ge=256, le=2048, json_schema_extra=_ADVANCED
    )

    @field_validator("s3_bucket")
    @classmethod
    def _bucket(cls, value: str) -> str:
        if not value or "/" in value or value in {".", ".."}:
            raise ValueError("S3 bucket must be one path segment")
        return value

    @field_validator("s3_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        if {".", ".."}.intersection(_segments(value)):
            raise ValueError("S3 prefix must omit dot segments")
        return value


class ExportLabelStudioInput(NodeInput):
    regions: TiffTextRegions = Field(title="Text regions")
    scores: Table | None = Field(default=None, title="Jev scores")


class ExportLabelStudioOutput(NodeOutput):
    summary: Table


class ImportLabelStudioConfig(_LabelStudioConfig):
    project_id: int | None = Field(default=None, gt=0)
    keep_labels: str = "settlement_or_place_name,other_text,text"
    only_annotated: bool = True
    page: int = Field(default=0, ge=0)


class ImportLabelStudioInput(NodeInput):
    source: Ref[TiffFile] = Field(title="Source TIFF")


class ImportLabelStudioOutput(NodeOutput):
    regions: TiffTextRegions
    annotations: Table


def _s3_object_url(
    base: AnyHttpUrl, config: ExportLabelStudioConfig, key: str
) -> httpx.URL:
    parts = [config.s3_bucket, *_segments(config.s3_prefix), f"{key}.png"]
    suffix = "/".join(quote(part, safe="-_.~") for part in parts)
    return httpx.URL(f"{str(base).rstrip('/')}/{suffix}")


def _sign_s3_put(
    url: httpx.URL,
    payload: bytes,
    *,
    access_key: str,
    secret_key: SecretStr,
    region: str,
    now: datetime,
) -> dict[str, str]:
    timestamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    date = timestamp[:8]
    content_hash = sha256(payload).hexdigest()
    scope = f"{date}/{region}/s3/aws4_request"
    headers = {
        "content-type": "image/png",
        "host": url.netloc.decode("ascii"),
        "x-amz-content-sha256": content_hash,
        "x-amz-date": timestamp,
    }
    signed = ";".join(headers)
    canonical_headers = "".join(f"{name}:{value}\n" for name, value in headers.items())
    path = url.raw_path.decode("ascii")
    canonical_request = "\n".join(
        ["PUT", path, "", canonical_headers, signed, content_hash]
    )
    algorithm = "AWS4-HMAC-SHA256"
    request_hash = sha256(canonical_request.encode()).hexdigest()
    string_to_sign = "\n".join([algorithm, timestamp, scope, request_hash])
    signing_key = f"AWS4{secret_key.get_secret_value()}".encode()
    for part in (date, region, "s3", "aws4_request"):
        signing_key = hmac_digest(signing_key, part.encode(), "sha256")
    signature = hmac_digest(signing_key, string_to_sign.encode(), "sha256").hex()
    headers["authorization"] = (
        f"{algorithm} Credential={access_key}/{scope}, SignedHeaders={signed}, "
        f"Signature={signature}"
    )
    return headers


@asynccontextmanager
async def _http_client(
    injected: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    if injected is not None:
        yield injected
        return
    async with httpx.AsyncClient(
        transport=PinnedPublicAddressTransport(), trust_env=False
    ) as client:
        yield client


def _check_response(response: httpx.Response, service: str) -> None:
    if not response.is_success:
        raise UserFacingNodeError(f"{service} returned HTTP {response.status_code}")


class _Project(BaseModel):
    id: int
    title: str


class _AccessToken(BaseModel):
    access: str = Field(min_length=1)


class _TaskImport(BaseModel):
    task_ids: tuple[int]


class _Result(BaseModel):
    type: str
    value: dict[str, object]


class _Review(BaseModel):
    id: int = 0
    was_cancelled: bool = False
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    result: list[_Result] = Field(default_factory=list)

    @property
    def timestamp(self) -> datetime | None:
        return self.updated_at or self.created_at


class _Task(BaseModel):
    id: int
    data: dict[str, object]
    annotations: list[_Review] = Field(default_factory=list)
    predictions: list[_Review] = Field(default_factory=list)


class _Page[T](BaseModel):
    items: list[T] = Field(validation_alias=AliasChoices("results", "tasks"))
    total: int | None = Field(
        default=None, validation_alias=AliasChoices("total", "count")
    )
    next: str | None = None


_PROJECTS: TypeAdapter[list[_Project] | _Page[_Project]] = TypeAdapter(
    list[_Project] | _Page[_Project]
)
_TASKS: TypeAdapter[list[_Task] | _Page[_Task]] = TypeAdapter(
    list[_Task] | _Page[_Task]
)
_ACCESS_TOKEN = TypeAdapter(_AccessToken)
_PROJECT = TypeAdapter(_Project)
_TASK_IMPORT = TypeAdapter(_TaskImport)


class _LabelStudio:
    def __init__(
        self, client: httpx.AsyncClient, config: _LabelStudioConfig, token: SecretStr
    ) -> None:
        self.client = client
        self.base = str(config.label_studio_url).rstrip("/")
        self.timeout = config.timeout_ms / 1000
        self.token = token
        self._authorization: str | None = None

    async def authenticate(self) -> None:
        token = self.token.get_secret_value()
        parts = token.split(".")
        if len(parts) == 3 and all(parts):
            access = await self.request(
                _ACCESS_TOKEN, "POST", "/api/token/refresh/", payload={"refresh": token}
            )
            self._authorization = f"Bearer {access.access}"
        else:
            self._authorization = f"Token {token}"

    async def request[T](
        self,
        adapter: TypeAdapter[T],
        method: str,
        path: str,
        *,
        payload: object = None,
        params: dict[str, str | int] | None = None,
    ) -> T:
        headers = {"Authorization": self._authorization} if self._authorization else {}
        try:
            response = await self.client.request(
                method,
                self.base + path,
                headers=headers,
                json=payload,
                params=params,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except EgressRejectedError as exc:
            raise UserFacingNodeError(
                "Label Studio may not be dialed by this deployment"
            ) from exc
        except httpx.RequestError as exc:
            raise UserFacingNodeError("Could not reach Label Studio") from exc
        _check_response(response, "Label Studio")
        try:
            return adapter.validate_json(response.content)
        except ValidationError as exc:
            raise UserFacingNodeError(
                "Label Studio returned an unexpected response"
            ) from exc

    async def _pages[T](
        self,
        adapter: TypeAdapter[list[T] | _Page[T]],
        path: str,
        **params: str | int,
    ) -> AsyncIterator[T]:
        seen = 0
        for page in count(1):
            result = await self.request(
                adapter,
                "GET",
                path,
                params={**params, "page_size": _PAGE_SIZE, "page": page},
            )
            if isinstance(result, list):
                for item in result:
                    yield item
                return
            for item in result.items:
                yield item
            seen += len(result.items)
            # Rebuild pagination requests against the configured endpoint. A next
            # link supplied by the server never determines where the token is sent.
            if not result.items or (not result.next and seen >= (result.total or 0)):
                return

    async def find_project(self, title: str) -> int | None:
        async for project in self._pages(_PROJECTS, "/api/projects/"):
            if project.title == title:
                return project.id
        return None

    def tasks(self, project_id: int) -> AsyncIterator[_Task]:
        return self._pages(_TASKS, "/api/tasks/", project=project_id, fields="all")

    async def import_task(self, project_id: int, task: dict[str, object]) -> int:
        result = await self.request(
            _TASK_IMPORT,
            "POST",
            f"/api/projects/{project_id}/import",
            payload=[task],
            params={"return_task_ids": "true"},
        )
        return result.task_ids[0]


type _Probability = Annotated[float, Field(ge=0, le=1, strict=True)]


class _JevScore(BaseModel):
    region_index: Annotated[int, Field(ge=0, strict=True)]
    p_text: _Probability
    predicted_kind: str
    triage_band: Literal["review", "prelabel", "auto_drop"]
    uncertainty: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]
    p_settlement: _Probability | None = None
    p_other_text: _Probability | None = None
    p_trees: _Probability | None = None
    p_other_symbol: _Probability | None = None

    def confidence(self) -> float:
        probabilities = {
            "settlement_or_place_name": self.p_settlement,
            "other_text": self.p_other_text,
            "trees_or_vegetation": self.p_trees,
            "other_symbol_or_artifact": self.p_other_symbol,
        }
        probability = probabilities[self.predicted_kind]
        if probability is not None:
            return probability
        if self.predicted_kind in {"settlement_or_place_name", "other_text"}:
            return self.p_text
        return 1 - self.p_text


@dataclass(frozen=True, slots=True)
class _ScoredRegion:
    region: TextRegion
    score: _JevScore | None


def _scored_regions(inputs: ExportLabelStudioInput) -> list[_ScoredRegion]:
    scores: dict[int, _JevScore] = {}
    if inputs.scores is not None:
        try:
            for row in inputs.scores.rows:
                score = _JevScore.model_validate(row)
                if score.region_index in scores:
                    raise ValueError("Repeated region index")
                scores[score.region_index] = score
        except ValueError as exc:
            raise UserFacingNodeError(
                "Scores must contain one Jev row per scored region index"
            ) from exc
    regions = [
        _ScoredRegion(region, scores.get(index))
        for index, region in enumerate(inputs.regions.regions)
    ]
    priority = {"review": 0, "prelabel": 1, "auto_drop": 2}

    def sort_key(region: _ScoredRegion) -> tuple[int, float]:
        score = region.score
        return (
            (3, 0)
            if score is None
            else (priority[score.triage_band], -score.uncertainty)
        )

    return sorted(regions, key=sort_key)


def _extents(polygon: PixelPolygon) -> tuple[float, float, float, float]:
    xs, ys = zip(*polygon, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _bounds(polygon: PixelPolygon) -> Window:
    left, top, right, bottom = _extents(polygon)
    col, row = floor(left), floor(top)
    return Window(col, row, max(1, ceil(right) - col), max(1, ceil(bottom) - row))


def _crop_axis(
    start: int, end: int, limit: int, config: ExportLabelStudioConfig
) -> tuple[int, int]:
    padding = config.context_padding_px
    extent = min(limit, max(config.min_crop_edge_px, end - start + 2 * padding))
    origin = min(limit - extent, max(0, (start + end - extent) // 2))
    return origin, extent


def _tile_axis(start: int, end: int, limit: int, edge: int) -> tuple[int, int]:
    # Shift a grid tile when it would cut through its assigned region.
    origin = max(start // edge * edge, end - edge)
    origin = min(start, origin)
    return origin, min(limit - origin, max(edge, end - origin))


@dataclass(frozen=True, slots=True)
class _ExportTask:
    window: Window
    regions: Sequence[_ScoredRegion]


def _plan_tasks(
    regions: Sequence[_ScoredRegion], page: TiffPage, config: ExportLabelStudioConfig
) -> list[_ExportTask]:
    crops: list[_ExportTask] = []
    tiles: dict[Window, list[_ScoredRegion]] = {}
    for region in regions:
        box = _bounds(region.region.polygon)
        if box.right > page.width or box.bottom > page.height:
            raise UserFacingNodeError(
                "A text polygon extends outside its source TIFF page"
            )
        if config.mode == _CROPS:
            col, width = _crop_axis(box.col, box.right, page.width, config)
            row, height = _crop_axis(box.row, box.bottom, page.height, config)
            crops.append(_ExportTask(Window(col, row, width, height), [region]))
        else:
            col, width = _tile_axis(box.col, box.right, page.width, config.tile_edge_px)
            row, height = _tile_axis(
                box.row, box.bottom, page.height, config.tile_edge_px
            )
            tiles.setdefault(Window(col, row, width, height), []).append(region)
    if config.mode == _CROPS:
        return crops
    return [_ExportTask(window, members) for window, members in tiles.items()]


async def _read_raw_png(page: TiffPage, window: Window) -> bytes:
    col, row, width, height = window.col, window.row, window.width, window.height
    if width * height <= _NATIVE_CROP_PIXEL_LIMIT:
        return await page.read(col=col, row=row, width=width, height=height)

    if width * height > 64 * _NATIVE_CROP_PIXEL_LIMIT:
        raise UserFacingNodeError(
            "A Label Studio image exceeds the TIFF window size limit"
        )
    edge = floor(_NATIVE_CROP_PIXEL_LIMIT**0.5)
    with Image.new("RGBA", (width, height)) as canvas:
        for y in range(0, height, edge):
            for x in range(0, width, edge):
                chunk = await page.read(
                    col=col + x,
                    row=row + y,
                    width=min(edge, width - x),
                    height=min(edge, height - y),
                )
                with Image.open(BytesIO(chunk)) as image:
                    canvas.paste(image.convert("RGBA"), (x, y))
        output = BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()


async def _read_png(
    page: TiffPage, window: Window, polygon: PixelPolygon | None = None
) -> bytes:
    raw = await _read_raw_png(page, window)
    if polygon is None:
        return raw
    points = [(x - window.col, y - window.row) for x, y in polygon]
    with Image.open(BytesIO(raw)) as loaded:
        rgb = loaded.convert("RGB")
    try:
        draw = ImageDraw.Draw(rgb)
        draw.line([*points, points[0]], fill=_MAGENTA, width=2, joint="curve")
        output = BytesIO()
        rgb.save(output, format="PNG")
        return output.getvalue()
    finally:
        rgb.close()


def _percent_point(point: PixelPoint, window: Window) -> tuple[float, float]:
    x, y = point
    return (
        (x - window.col) * 100 / window.width,
        (y - window.row) * 100 / window.height,
    )


def _predictions(
    members: Sequence[_ScoredRegion], mode: ExportMode, window: Window
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    confidences: list[float] = []
    has_jev = False
    for index, member in enumerate(members):
        score = member.score
        if score is None:
            if mode == _CROPS:
                continue
            label = "other_text"
            confidence = 0.5
        elif score.predicted_kind not in _LABEL_COLORS:
            continue
        else:
            has_jev = True
            label = score.predicted_kind
            confidence = score.confidence()
        if mode == _CROPS:
            result = {
                "type": "choices",
                "from_name": "kind",
                "value": {"choices": [label]},
            }
        else:
            result = {
                "type": "polygonlabels",
                "from_name": "label",
                "original_width": window.width,
                "original_height": window.height,
                "image_rotation": 0,
                "value": {
                    "points": [
                        _percent_point(point, window) for point in member.region.polygon
                    ],
                    "polygonlabels": [label],
                },
            }
        results.append(
            {**result, "id": f"jev_{index}", "to_name": "image", "score": confidence}
        )
        confidences.append(confidence)
    if not results:
        return []
    return [
        {
            "result": results,
            "model_version": "jev-1.14.0" if has_jev else "craft",
            "score": sum(confidences) / len(confidences),
        }
    ]


def _table(rows: list[dict[str, TableValue]], **columns: TableValueType) -> Table:
    return Table(
        columns=[
            TableColumn(
                id=name, title=name.replace("_", " ").capitalize(), value_type=kind
            )
            for name, kind in columns.items()
        ],
        rows=rows,
    )


async def _open_tiff(
    opener: TiffPageOpener | None,
    context: NodeExecutionContext,
    source: Ref[TiffFile],
    page: int,
) -> TiffPage:
    if opener is None:
        raise UserFacingNodeError("TIFF window reading is unavailable")
    return await opener(context.workspace_id, source.artifact_id, page=page)


@OCR.node(
    operator_id="ocr.export_label_studio",
    version=1,
    title="Export TIFF regions to Label Studio",
    required_capabilities=_CAPABILITIES,
    http_egress=NodeHttpEgressContract(
        configured_inputs=(
            NodeHttpEgressInput(config_field="label_studio_url"),
            NodeHttpEgressInput(config_field="s3_endpoint_url"),
        )
    ),
    secret_inputs=(_LS_TOKEN, _S3_SECRET),
    cache_policy=NodeCachePolicy.NEVER,
    factory=lambda context: ExportLabelStudioNode(context.open_tiff_page),
)
@final
class ExportLabelStudioNode(
    Node[ExportLabelStudioConfig, ExportLabelStudioInput, ExportLabelStudioOutput]
):
    def __init__(
        self,
        open_page: TiffPageOpener | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._open_page = open_page
        self._client = client

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ExportLabelStudioConfig,
        inputs: ExportLabelStudioInput,
        /,
    ) -> ExportLabelStudioOutput:
        detected = inputs.regions
        page = await _open_tiff(
            self._open_page, context, detected.source, detected.window.page
        )
        candidates = _plan_tasks(_scored_regions(inputs), page, config)
        token = await context.secrets.require(_LS_TOKEN.name)
        s3_secret = await context.secrets.require(_S3_SECRET.name)
        async with _http_client(self._client) as client:
            studio = _LabelStudio(client, config, token)
            lock_key = (get_running_loop(), studio.base, config.project_title)
            async with _PROJECT_LOCKS.setdefault(lock_key, Lock()):
                await studio.authenticate()
                rows = await _export_tasks(studio, config, page, candidates, s3_secret)
        return ExportLabelStudioOutput(
            summary=_table(
                rows,
                project_id=TableValueType.INTEGER,
                task_id=TableValueType.INTEGER,
                grafy_key=TableValueType.TEXT,
                status=TableValueType.TEXT,
                triage_band=TableValueType.TEXT,
                p_text=TableValueType.NUMBER,
                uncertainty=TableValueType.NUMBER,
                predicted_kind=TableValueType.TEXT,
                image_url=TableValueType.TEXT,
                project_url=TableValueType.TEXT,
            )
        )


async def _export_tasks(
    studio: _LabelStudio,
    config: ExportLabelStudioConfig,
    page: TiffPage,
    candidates: Sequence[_ExportTask],
    s3_secret: SecretStr,
) -> list[dict[str, TableValue]]:
    project_id = await studio.find_project(config.project_title)
    if project_id is None:
        project = await studio.request(
            _PROJECT,
            "POST",
            "/api/projects/",
            payload={
                "title": config.project_title,
                "label_config": _LABEL_CONFIGS[config.mode],
            },
        )
        project_id = project.id
    existing: dict[str, tuple[int, str | None]] = {}
    async for task in studio.tasks(project_id):
        key, image = task.data.get("grafy_key"), task.data.get("image")
        if isinstance(key, str):
            existing[key] = (task.id, image if isinstance(image, str) else None)

    rows: list[dict[str, TableValue]] = []
    exported = 0
    for candidate in candidates:
        window = candidate.window
        polygon = candidate.regions[0].region.polygon if config.mode == _CROPS else None
        geometry = (
            polygon
            if polygon is not None
            else (window.col, window.row, window.width, window.height)
        )
        key = sha256(
            dumps([page.source_sha256, page.page, config.mode, geometry]).encode()
        ).hexdigest()
        members = [
            member
            for member in candidate.regions
            if not (
                config.skip_auto_drop
                and member.score
                and member.score.triage_band == "auto_drop"
            )
        ]
        score = (members or candidate.regions)[0].score
        task_id: int | None = None
        image_url: str | None = None
        if not members:
            status = "skipped_auto_drop"
        elif key in existing:
            task_id, image_url = existing[key]
            status = "skipped_existing"
        elif exported >= config.max_tasks:
            continue
        else:
            image_url = str(_s3_object_url(config.s3_public_url, config, key))
            data: dict[str, object] = {
                "grafy_key": key,
                "source_sha256": page.source_sha256,
                "page": page.page,
                "mode": config.mode,
                "tile_col": window.col,
                "tile_row": window.row,
                "tile_width": window.width,
                "tile_height": window.height,
                "image": image_url,
            }
            if polygon is not None:
                data["polygon"] = polygon
                if score is not None:
                    data["triage_band"] = score.triage_band
                    data["predicted_kind"] = score.predicted_kind
                    data["p_text"] = score.p_text
                    data["uncertainty"] = score.uncertainty
                    data["triage_summary"] = (
                        f"{score.triage_band} · {score.predicted_kind} · "
                        f"p(text) {score.p_text:.2f} · uncertainty {score.uncertainty:.2f}"
                    )
                else:
                    data["triage_summary"] = "Unscored"
            predictions = _predictions(members, config.mode, window)
            if predictions and polygon is None:
                # Recover untouched vertices exactly even when converting a pixel
                # coordinate to a percentage changed its floating-point value.
                data["jev_polygons"] = [
                    member.region.polygon
                    for member in members
                    if member.score is None
                    or member.score.predicted_kind in _LABEL_COLORS
                ]
            payload: dict[str, object] = {"data": data}
            if predictions:
                payload["predictions"] = predictions
            await _upload_png(studio, config, page, window, polygon, key, s3_secret)
            task_id = await studio.import_task(project_id, payload)
            existing[key] = (task_id, image_url)
            exported += 1
            status = "exported"
        rows.append(
            {
                "project_id": project_id,
                "task_id": task_id,
                "grafy_key": key,
                "status": status,
                "triage_band": score.triage_band if score else None,
                "p_text": score.p_text if score else None,
                "uncertainty": score.uncertainty if score else None,
                "predicted_kind": score.predicted_kind if score else None,
                "image_url": image_url,
                "project_url": f"{studio.base}/projects/{project_id}/data",
            }
        )
    return rows


async def _upload_png(
    studio: _LabelStudio,
    config: ExportLabelStudioConfig,
    page: TiffPage,
    window: Window,
    polygon: PixelPolygon | None,
    key: str,
    secret: SecretStr,
) -> None:
    url = _s3_object_url(config.s3_endpoint_url, config, key)
    png = await _read_png(page, window, polygon)
    headers = _sign_s3_put(
        url,
        png,
        access_key=config.s3_access_key,
        secret_key=secret,
        region=config.s3_region,
        now=datetime.now(UTC),
    )
    try:
        response = await studio.client.put(
            url,
            content=png,
            headers=headers,
            timeout=studio.timeout,
            follow_redirects=False,
        )
    except EgressRejectedError as exc:
        raise UserFacingNodeError(
            "MinIO / S3 may not be dialed by this deployment"
        ) from exc
    except httpx.RequestError as exc:
        raise UserFacingNodeError("Could not reach MinIO / S3") from exc
    _check_response(response, "MinIO / S3")


type _Percent = Annotated[float, Field(ge=0, le=100, strict=True)]
type _PercentPoint = tuple[_Percent, _Percent]
type _PercentPoints = Annotated[list[_PercentPoint], Field(min_length=3)]


class _TileData(BaseModel):
    tile_col: int = Field(ge=0)
    tile_row: int = Field(ge=0)
    tile_width: int = Field(gt=0)
    tile_height: int = Field(gt=0)
    jev_polygons: list[PixelPolygon] = Field(default_factory=list)

    def window(self) -> Window:
        return Window(self.tile_col, self.tile_row, self.tile_width, self.tile_height)


class _Rectangle(BaseModel):
    x: _Percent
    y: _Percent
    width: _Percent
    height: _Percent
    rotation: Annotated[float, Field(allow_inf_nan=False)] = 0

    def points(self, window: Window) -> PixelPolygon:
        # Label Studio rotates around the top-left corner in image pixels.
        x = self.x * window.width / 100 + window.col
        y = self.y * window.height / 100 + window.row
        width = self.width * window.width / 100
        height = self.height * window.height / 100
        angle = radians(self.rotation)
        return [
            (
                x + dx * cos(angle) - dy * sin(angle),
                y + dx * sin(angle) + dy * cos(angle),
            )
            for dx, dy in [(0, 0), (width, 0), (width, height), (0, height)]
        ]


_POLYGON: TypeAdapter[PixelPolygon] = TypeAdapter(PixelPolygon)
_PERCENT_POINTS: TypeAdapter[_PercentPoints] = TypeAdapter(_PercentPoints)
_LABELS = TypeAdapter(list[str])
_OLDEST = datetime.min.replace(tzinfo=UTC)


def _review_order(review: _Review) -> tuple[datetime, int]:
    return review.timestamp or _OLDEST, review.id


def _result_polygon(result: _Result, data: dict[str, object]) -> PixelPolygon:
    if result.type == "choices":
        return _POLYGON.validate_python(data.get("polygon"))
    tile = _TileData.model_validate(data)
    window = tile.window()
    if result.type == "rectanglelabels":
        return _Rectangle.model_validate(result.value).points(window)
    points = _PERCENT_POINTS.validate_python(result.value.get("points"))
    original = {
        _percent_point(point, window): point
        for polygon in tile.jev_polygons
        for point in polygon
    }
    return [
        original.get(
            point,
            (
                point[0] * window.width / 100 + window.col,
                point[1] * window.height / 100 + window.row,
            ),
        )
        for point in points
    ]


@OCR.node(
    operator_id="ocr.import_label_studio",
    version=1,
    title="Import Label Studio annotations",
    required_capabilities=_CAPABILITIES,
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="label_studio_url"),)
    ),
    secret_inputs=(_LS_TOKEN,),
    cache_policy=NodeCachePolicy.NEVER,
    factory=lambda context: ImportLabelStudioNode(context.open_tiff_page),
)
@final
class ImportLabelStudioNode(
    Node[ImportLabelStudioConfig, ImportLabelStudioInput, ImportLabelStudioOutput]
):
    def __init__(
        self,
        open_page: TiffPageOpener | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._open_page = open_page
        self._client = client

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ImportLabelStudioConfig,
        inputs: ImportLabelStudioInput,
        /,
    ) -> ImportLabelStudioOutput:
        page = await _open_tiff(self._open_page, context, inputs.source, config.page)
        token = await context.secrets.require(_LS_TOKEN.name)
        async with _http_client(self._client) as client:
            studio = _LabelStudio(client, config, token)
            await studio.authenticate()
            project_id = config.project_id or await studio.find_project(
                config.project_title
            )
            if project_id is None:
                raise UserFacingNodeError("Label Studio project was not found")
            regions, rows = await _import_regions(studio, project_id, config, page)
        bounds = (
            _bounds([point for region in regions for point in region.polygon])
            if regions
            else Window(0, 0, 1, 1)
        )
        return ImportLabelStudioOutput(
            regions=TiffTextRegions(
                source=inputs.source,
                regions=regions,
                window=TiffPixelWindow(
                    page=config.page,
                    col=bounds.col,
                    row=bounds.row,
                    width=bounds.width,
                    height=bounds.height,
                ),
            ),
            annotations=_table(
                rows,
                task_id=TableValueType.INTEGER,
                grafy_key=TableValueType.TEXT,
                human_label=TableValueType.TEXT,
                page=TableValueType.INTEGER,
                x=TableValueType.NUMBER,
                y=TableValueType.NUMBER,
                width=TableValueType.NUMBER,
                height=TableValueType.NUMBER,
                from_annotation=TableValueType.BOOLEAN,
                updated_at=TableValueType.DATETIME,
            ),
        )


async def _import_regions(
    studio: _LabelStudio,
    project_id: int,
    config: ImportLabelStudioConfig,
    page: TiffPage,
) -> tuple[list[TextRegion], list[dict[str, TableValue]]]:
    keep = {label.strip() for label in config.keep_labels.split(",") if label.strip()}
    regions: list[TextRegion] = []
    rows: list[dict[str, TableValue]] = []
    async for task in studio.tasks(project_id):
        key = task.data.get("grafy_key")
        if (
            not isinstance(key, str)
            or task.data.get("source_sha256") != page.source_sha256
            or task.data.get("page") != config.page
        ):
            continue
        review = max(
            (item for item in task.annotations if not item.was_cancelled),
            key=_review_order,
            default=None,
        )
        from_annotation = review is not None
        if review is None and not config.only_annotated:
            review = max(task.predictions, key=_review_order, default=None)
        if review is None:
            continue
        for result in review.result:
            if result.type not in {"choices", "polygonlabels", "rectanglelabels"}:
                continue
            try:
                labels = _LABELS.validate_python(result.value.get(result.type, []))
                selected = [label for label in labels if label in keep]
                if not selected:
                    continue
                region = TextRegion(polygon=_result_polygon(result, task.data))
            except ValidationError as exc:
                raise UserFacingNodeError(
                    f"Label Studio task {task.id} contains invalid region data"
                ) from exc
            left, top, right, bottom = _extents(region.polygon)
            for label in selected:
                regions.append(region)
                rows.append(
                    {
                        "task_id": task.id,
                        "grafy_key": key,
                        "human_label": label,
                        "page": config.page,
                        "x": left,
                        "y": top,
                        "width": right - left,
                        "height": bottom - top,
                        "from_annotation": from_annotation,
                        "updated_at": review.timestamp.isoformat()
                        if review.timestamp is not None
                        else None,
                    }
                )
    return regions, rows
