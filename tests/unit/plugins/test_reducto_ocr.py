"""The Reducto OCR node, driven through `run` against a stand-in Reducto."""

import asyncio
import io
import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import cast, final
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr, TypeAdapter, ValidationError

from grafy_core import egress
from grafy_core.artifact_contracts import MARKDOWN, RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.egress import EgressPolicy, PinnedPublicAddressTransport
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import (
    PluginRegistry,
    PluginRuntimeContext,
    PluginUnitOfWorkPort,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.table_contracts import TABLE_DATA

from grafy_plugin_reducto import ocr
from grafy_plugin_reducto.declaration import REDUCTO
from grafy_plugin_reducto.ocr import (
    ReductoOcrConfig,
    ReductoOcrError,
    ReductoOcrInput,
    ReductoOcrNode,
    ReductoOcrOutput,
    build_parse_output,
)
from grafy_plugin_reducto.plugin import REDUCTO as INSTALLED
from grafy_plugin_reducto.response import ParseChunk, ParseChunkList

PLATFORM_HOST = "platform.reducto.ai"
STORAGE_HOST = "provider-storage.test"
RESULT_PATH = "/results/result-1.json"
STORAGE_URL = f"https://{STORAGE_HOST}{RESULT_PATH}"
API_KEY = "sek_reducto_test_key"
DOCUMENT_URL = "https://documents.example.test/report.pdf"
RASTER = b"\x89PNG\r\n\x1a\n a raster artifact"
REQUEST_BODY = TypeAdapter(dict[str, object])


def chunk_document(content: str, *, kind: str = "Title") -> dict[str, object]:
    box = {"left": 0.0, "top": 0.1, "width": 0.5, "height": 0.2, "page": 1}
    block = {"type": kind, "content": content, "bbox": box}
    return {"content": content, "embed": content, "blocks": [block]}


def inline_body(chunks: list[dict[str, object]]) -> dict[str, object]:
    return {"job_id": "job-1", "result": {"type": "full", "chunks": chunks}}


def url_body(url: str) -> dict[str, object]:
    return {"job_id": "job-1", "result": {"type": "url", "url": url}}


@final
class FakeReducto:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.parse_bodies: list[dict[str, object]] = []
        self.upload_bodies: list[bytes] = []
        self.parse_status = 200
        self.parse_body: Callable[[str], dict[str, object]] | None = None
        self.parse_arrived: dict[str, asyncio.Event] = {}
        self.parse_gate: asyncio.Event | None = None
        self.upload_file_id = "reducto://file-1"
        self.result_status = 200
        self.result_headers: dict[str, str] = {}
        self.result_body: bytes | None = None
        self.result_document: object = [chunk_document("# Document")]

    def to(self, path: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == path]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/parse":
            return await self._parse(request)
        if request.url.path == "/upload":
            self.upload_bodies.append(request.content)
            return httpx.Response(200, json={"file_id": self.upload_file_id})
        headers = self.result_headers
        if self.result_status != 200:
            return httpx.Response(self.result_status, headers=headers, json={})
        if self.result_body is not None:
            return httpx.Response(200, headers=headers, content=self.result_body)
        return httpx.Response(200, headers=headers, json=self.result_document)

    async def _parse(self, request: httpx.Request) -> httpx.Response:
        body = REQUEST_BODY.validate_json(request.content)
        self.parse_bodies.append(body)
        source = str(body["input"])
        arrived = self.parse_arrived.get(source)
        if arrived is not None:
            arrived.set()
        if self.parse_gate is not None:
            await self.parse_gate.wait()
        if self.parse_status == 200:
            if self.parse_body is not None:
                return httpx.Response(200, json=self.parse_body(source))
            chunks = [chunk_document(f"document of {source}")]
            return httpx.Response(200, json=inline_body(chunks))
        # The provider's own words, which this node must not carry onward.
        message = f"could not fetch {source} for report.pdf"
        error = {"code": "invalid_document_url", "message": message}
        return httpx.Response(self.parse_status, json={"error": error})


@final
class _FakeArtifactRepository:
    def __init__(self, artifact: ArtifactObject) -> None:
        self.artifact = artifact
        self.lookups: list[tuple[UUID, UUID]] = []

    async def get(self, workspace_id: UUID, artifact_id: UUID) -> ArtifactObject | None:
        self.lookups.append((workspace_id, artifact_id))
        found = self.artifact
        if found.id != artifact_id or found.workspace_id != workspace_id:
            return None
        return found


@final
class _FakeUnitOfWork:
    def __init__(self, artifacts: _FakeArtifactRepository) -> None:
        self.artifacts = artifacts

    async def __aenter__(self) -> "_FakeUnitOfWork":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


@final
class _FakeStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.error: Exception | None = None

    async def load(self, *, bucket: str, path: str) -> io.BytesIO:
        if self.error is not None:
            raise self.error
        return io.BytesIO(self.content)


@final
class RecordingSecrets:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.lookups: list[dict[str, object]] = []

    async def resolve_secret(self, **kwargs: object) -> SecretStr:
        self.lookups.append(kwargs)
        if self.error is not None:
            raise self.error
        return SecretStr(API_KEY)


def raster(workspace_id: UUID) -> ArtifactObject:
    return ArtifactObject(
        workspace_id=workspace_id,
        artifact_type="image.raster",
        schema_version=1,
        content_type="image/png",
        bucket="workbench-artifacts",
        object_key="objects/raster.png",
        byte_size=len(RASTER),
        sha256=sha256(RASTER).hexdigest(),
    )


async def await_event(event: asyncio.Event, *, within: float = 5.0) -> None:
    async with asyncio.timeout(within):
        await event.wait()


@final
class Env:
    def __init__(self) -> None:
        self.fake = FakeReducto()
        self.workspace_id = uuid4()
        self.context = NodeExecutionContext(
            self.workspace_id, uuid4(), "graph-1", "reducto-1"
        )
        self.artifact = raster(self.workspace_id)
        self.artifacts = _FakeArtifactRepository(self.artifact)
        self.storage = _FakeStorage(RASTER)
        self.secrets = RecordingSecrets()
        self.use_transport(httpx.MockTransport(self.fake.handle))

    def use_transport(self, transport: httpx.AsyncBaseTransport) -> None:
        self.node = ReductoOcrNode(
            uow=cast(UnitOfWorkPort, _FakeUnitOfWork(self.artifacts)),
            storage=cast(FileStoragePort, self.storage),
            node_secrets=cast(NodeSecretResolverPort, self.secrets),
            transport_factory=lambda: transport,
        )

    async def run(
        self,
        *,
        url: str | None = DOCUMENT_URL,
        image: ArtifactRef | None = None,
        config: ReductoOcrConfig | None = None,
    ) -> ReductoOcrOutput:
        return await self.node.run(
            self.context,
            ReductoOcrConfig() if config is None else config,
            ReductoOcrInput(document_url=url, image=image),
        )


@pytest.fixture
def env() -> Env:
    return Env()


def settings_of(body: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], body["settings"])


def bbox_json(**updates: object) -> dict[str, object]:
    return {"left": 0.1, "top": 0.2, "width": 0.3, "height": 0.4, "page": 1, **updates}


def block_json(**updates: object) -> dict[str, object]:
    return {"type": "Text", "content": "a paragraph", "bbox": bbox_json(), **updates}


def chunk_json(
    *, content: str = "chunk", blocks: list[object] | None = None, **extra: object
) -> dict[str, object]:
    return {
        "content": content,
        "blocks": [block_json()] if blocks is None else blocks,
        **extra,
    }


def parse_chunks(*payloads: object) -> list[ParseChunk]:
    return ParseChunkList.validate_python(list(payloads))


def test_the_family_installs_with_one_operator() -> None:
    registry = PluginRegistry()
    registry.install(INSTALLED)
    registry.freeze()
    keys = {registration.key for registration in REDUCTO.nodes}
    assert REDUCTO.slug == "external.reducto"
    assert keys == {("reducto.ocr.process", 1)}


def test_the_node_declares_exactly_its_ports(env: Env) -> None:
    made = env.node.output_contract.ports
    took = env.node.input_contract.ports
    assert [(port.name, port.produces) for port in made.values()] == [
        ("markdown", MARKDOWN.key),
        ("blocks", TABLE_DATA.key),
    ]
    assert [(port.name, port.accepts) for port in took.values()] == [
        ("document_url", TEXT_VALUE.key),
        ("image", RASTER_IMAGE.key),
    ]


def test_the_family_needs_egress_and_secrets_and_owns_the_markdown_writer() -> None:
    registration = REDUCTO.nodes[0]
    assert REDUCTO.capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    )
    assert registration.required_capabilities == REDUCTO.capabilities
    runtime = PluginRuntimeContext(
        Path("/tmp/grafy-reducto-test"),
        cast(FileStoragePort, object()),
        cast(PluginUnitOfWorkPort, object()),
        "workbench-artifacts",
    )
    writers = [factory(runtime) for factory in REDUCTO.writer_factories]
    assert [writer.artifact_type for writer in writers] == [MARKDOWN.key]


def test_the_family_declares_one_secret_and_its_destinations() -> None:
    registration = REDUCTO.nodes[0]
    destinations = registration.http_egress
    assert [secret.name for secret in registration.secret_inputs] == ["api_key"]
    assert registration.secret_inputs[0].config_dependencies == ()
    assert destinations is not None
    assert destinations.fixed_destinations == (ocr.REDUCTO_BASE_URL,)
    assert destinations.dynamic_destinations


def test_config_defaults_to_the_pinned_model_markdown_and_five_minutes() -> None:
    config = ReductoOcrConfig()
    assert (config.model, config.table_format, config.timeout_s) == ("r-1", "md", 300)
    assert config.page_start is None and config.page_end is None


@pytest.mark.parametrize("timeout_s", [10, 900])
def test_config_accepts_its_timeout_bounds(timeout_s: int) -> None:
    assert ReductoOcrConfig(timeout_s=timeout_s).timeout_s == timeout_s


@pytest.mark.parametrize("timeout_s", [9, 901])
def test_config_refuses_timeouts_outside_its_bounds(timeout_s: int) -> None:
    with pytest.raises(ValidationError):
        ReductoOcrConfig(timeout_s=timeout_s)


def test_config_pages_are_positive_and_ordered() -> None:
    with pytest.raises(ValidationError, match="page_end"):
        ReductoOcrConfig(page_start=4, page_end=3)
    with pytest.raises(ValidationError):
        ReductoOcrConfig(page_start=0)
    with pytest.raises(ValidationError):
        ReductoOcrConfig(page_end=0)


async def test_no_inputs_and_both_inputs_are_answered_locally(env: Env) -> None:
    both = ReductoOcrInput(document_url=DOCUMENT_URL, image=env.artifact.ref())
    for inputs in (ReductoOcrInput(), both):
        with pytest.raises(ReductoOcrError, match="exactly one"):
            await env.node.run(env.context, ReductoOcrConfig(), inputs)
    assert env.secrets.lookups == []
    assert env.fake.requests == []


@pytest.mark.parametrize(
    "url", ["http://x.test/a.pdf", "reducto://file-1", "jobid://abc", ""]
)
async def test_a_document_url_that_is_not_https_is_refused_unquoted(
    env: Env, url: str
) -> None:
    with pytest.raises(ReductoOcrError, match="must use HTTPS") as recorded:
        await env.run(url=url)
    assert url == "" or url not in str(recorded.value)
    assert env.secrets.lookups == []
    assert env.fake.requests == []


async def test_the_key_is_resolved_for_the_node_that_asked(env: Env) -> None:
    await env.run()
    assert env.secrets.lookups == [
        {
            "workspace_id": env.context.workspace_id,
            "project_id": env.context.project_id,
            "graph_id": env.context.graph_id,
            "node_id": env.context.node_id,
            "name": "api_key",
            "dependencies": {},
        }
    ]


async def test_a_failing_secret_resolver_stops_the_run(env: Env) -> None:
    env.secrets.error = RuntimeError("the secret store is down")
    with pytest.raises(ReductoOcrError, match="could not resolve"):
        await env.run()
    assert env.fake.requests == []


async def test_the_parse_request_is_exactly_the_decided_body(env: Env) -> None:
    await env.run(
        config=ReductoOcrConfig(model="r-1-mini", page_start=2, table_format="html")
    )
    assert env.fake.parse_bodies == [
        {
            "input": DOCUMENT_URL,
            "formatting": {"table_output_format": "html"},
            "retrieval": {"chunking": {"chunk_mode": "disabled", "chunk_overlap": 0}},
            "settings": {
                "model": "r-1-mini",
                "timeout": 300.0,
                "page_range": {"start": 2},
            },
        }
    ]


async def test_the_page_range_is_sent_only_when_it_is_set(env: Env) -> None:
    await env.run(config=ReductoOcrConfig(page_start=2, page_end=5))
    await env.run()
    first, second = env.fake.parse_bodies
    assert settings_of(first)["page_range"] == {"start": 2, "end": 5}
    assert "page_range" not in settings_of(second)


async def test_the_platform_is_dialed_with_the_nodes_own_key(env: Env) -> None:
    await env.run()
    request = env.fake.requests[0]
    assert request.url.host == PLATFORM_HOST
    assert request.headers["authorization"] == f"Bearer {API_KEY}"


@pytest.mark.parametrize(
    ("status", "fragment"), [(500, "HTTP 500"), (400, "HTTP 400"), (401, "API key")]
)
async def test_a_refusal_is_said_once_without_the_providers_own_words(
    env: Env, status: int, fragment: str
) -> None:
    env.fake.parse_status = status
    with pytest.raises(ReductoOcrError, match=fragment) as recorded:
        await env.run()
    message = str(recorded.value)
    assert len(env.fake.to("/parse")) == 1
    assert "could not fetch" not in message
    assert "invalid_document_url" not in message
    assert "report.pdf" not in message


async def test_an_uploaded_image_goes_as_its_own_bytes(env: Env) -> None:
    content = b"\x89PNG\r\n\x1a\n marker-bytes"
    env.storage.content = content
    env.artifact.sha256 = sha256(content).hexdigest()
    env.fake.upload_file_id = "reducto://file-9"
    output = await env.run(url=None, image=env.artifact.ref())
    body = env.fake.upload_bodies[0]
    assert content in body
    assert b'filename="document.png"' in body
    assert b"content-type: image/png" in body.lower()
    assert env.fake.parse_bodies[0]["input"] == "reducto://file-9"
    assert output.markdown.markdown == "document of reducto://file-9"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("content_type", "image/gif", "unsupported content type"),
        ("sha256", "0" * 64, "SHA-256 does not match"),
        ("workspace_id", uuid4(), "was not found"),
    ],
)
async def test_an_image_that_must_not_be_uploaded_stops_before_any_request(
    env: Env, field: str, value: object, reason: str
) -> None:
    setattr(env.artifact, field, value)
    with pytest.raises(ReductoOcrError, match=reason):
        await env.run(url=None, image=env.artifact.ref())
    assert env.artifacts.lookups == [(env.workspace_id, env.artifact.id)]
    assert env.fake.requests == []


async def test_a_source_above_the_product_limit_stops_before_any_request(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr, "MAX_SOURCE_BYTES", 8)
    with pytest.raises(ReductoOcrError, match="8-byte source limit"):
        await env.run(url=None, image=env.artifact.ref())
    assert env.fake.requests == []


async def test_an_unreadable_raster_names_no_storage_path(env: Env) -> None:
    env.storage.error = RuntimeError("no such workbench-artifacts/objects/raster.png")
    with pytest.raises(ReductoOcrError, match="could not read") as recorded:
        await env.run(url=None, image=env.artifact.ref())
    assert "workbench-artifacts" not in str(recorded.value)
    assert "objects/raster.png" not in str(recorded.value)
    assert env.fake.requests == []


async def test_inline_and_url_results_give_the_same_output(env: Env) -> None:
    inline = await env.run()
    other = Env()
    other.fake.parse_body = lambda source: url_body(STORAGE_URL)
    other.fake.result_document = [chunk_document(f"document of {DOCUMENT_URL}")]
    assert (await other.run()).model_dump() == inline.model_dump()


async def test_a_result_document_may_wrap_its_chunks_in_an_object(env: Env) -> None:
    env.fake.parse_body = lambda source: url_body(STORAGE_URL)
    env.fake.result_document = {"chunks": [chunk_document("# Document")]}
    output = await env.run()
    assert output.markdown.markdown == "# Document"


@pytest.mark.parametrize("via_url", [False, True])
async def test_an_unknown_block_kind_reaches_the_table(env: Env, via_url: bool) -> None:
    chunk = chunk_document("scrawled in the margin", kind="Handwritten Note")
    if via_url:
        env.fake.parse_body = lambda source: url_body(STORAGE_URL)
        env.fake.result_document = [chunk]
    else:
        env.fake.parse_body = lambda source: inline_body([chunk])
    output = await env.run()
    assert output.blocks.rows[0]["kind"] == "Handwritten Note"


async def test_the_storage_host_gets_neither_the_key_nor_a_cookie(env: Env) -> None:
    env.fake.parse_body = lambda source: url_body(STORAGE_URL)
    await env.run()
    stored = env.fake.to(RESULT_PATH)
    assert len(stored) == 1
    assert "authorization" not in stored[0].headers
    assert "cookie" not in stored[0].headers
    assert env.fake.requests[0].headers["authorization"] == f"Bearer {API_KEY}"


async def test_a_redirect_from_storage_is_not_followed(env: Env) -> None:
    env.fake.parse_body = lambda source: url_body(STORAGE_URL)
    env.fake.result_status = 302
    env.fake.result_headers = {"location": f"https://{STORAGE_HOST}/elsewhere.json"}
    with pytest.raises(ReductoOcrError, match="HTTP 302"):
        await env.run()
    assert len(env.fake.to(RESULT_PATH)) == 1
    assert env.fake.to("/elsewhere.json") == []


async def test_a_result_url_that_is_not_https_is_refused_unquoted(env: Env) -> None:
    url = f"http://{STORAGE_HOST}/result.json"
    env.fake.parse_body = lambda source: url_body(url)
    with pytest.raises(ReductoOcrError, match="not HTTPS") as recorded:
        await env.run()
    assert url not in str(recorded.value)
    assert [request.method for request in env.fake.requests] == ["POST"]


async def test_an_oversized_result_is_stopped_while_it_streams(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr, "MAX_RESULT_BYTES", 32)
    env.fake.parse_body = lambda source: url_body(STORAGE_URL)
    env.fake.result_body = b"x" * 90
    with pytest.raises(ReductoOcrError, match="32 bytes"):
        await env.run()


@pytest.mark.parametrize(
    "body",
    [
        b"<html>not json</html>",
        b'{"chunks": 5}',
        b'[{"content": "a chunk without its blocks"}]',
        b'"a bare string"',
    ],
)
async def test_a_result_document_that_is_not_the_chunk_contract_is_refused(
    env: Env, body: bytes
) -> None:
    env.fake.parse_body = lambda source: url_body(STORAGE_URL)
    env.fake.result_body = body
    with pytest.raises(ReductoOcrError, match="does not match the Parse contract"):
        await env.run()


@pytest.mark.parametrize(
    "document",
    [{"job_id": "job-1"}, {"job_id": "job-1", "result": {"type": "full"}}],
)
async def test_a_result_that_omits_its_contract_keys_is_refused(
    env: Env, document: dict[str, object]
) -> None:
    env.fake.parse_body = lambda source: document
    with pytest.raises(ReductoOcrError, match="does not match the Parse contract"):
        await env.run()


async def resolves_locally(
    host: str, port: int, timeout_seconds: float
) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(0, 0, 0, "", ("127.0.0.1", port))]


async def test_a_platform_dial_that_resolves_into_the_deployment_is_never_made(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(egress, "_lookup", resolves_locally)
    env.use_transport(
        PinnedPublicAddressTransport(
            policy=EgressPolicy.from_destinations(()),
            transport=httpx.MockTransport(env.fake.handle),
        )
    )
    with pytest.raises(ReductoOcrError, match="egress policy"):
        await env.run()
    assert env.fake.requests == []


async def test_a_result_download_that_resolves_into_the_deployment_is_never_made(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(egress, "_lookup", resolves_locally)
    env.fake.parse_body = lambda source: url_body(STORAGE_URL)
    env.use_transport(
        PinnedPublicAddressTransport(
            policy=EgressPolicy.from_destinations((PLATFORM_HOST,)),
            transport=httpx.MockTransport(env.fake.handle),
        )
    )
    with pytest.raises(ReductoOcrError, match="egress policy"):
        await env.run()
    assert len(env.fake.to("/parse")) == 1
    assert env.fake.to(RESULT_PATH) == []


async def test_a_cancelled_run_leaves_no_task_behind(env: Env) -> None:
    arrived = asyncio.Event()
    env.fake.parse_arrived[DOCUMENT_URL] = arrived
    env.fake.parse_gate = asyncio.Event()
    started = {
        task for task in asyncio.all_tasks() if task is not asyncio.current_task()
    }
    call = asyncio.create_task(env.run())
    await await_event(arrived)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    left = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    assert left == started


async def test_a_budget_that_expires_before_an_answer_is_a_budget(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole wait is timeout_s plus the grace, so a grace below zero moves the
    # deadline to a hair after the request is dialed.
    monkeypatch.setattr(ocr, "TIMEOUT_GRACE_SECONDS", -299.95)
    env.fake.parse_gate = asyncio.Event()
    with pytest.raises(ReductoOcrError, match="time budget") as recorded:
        await env.run()
    assert "does not resubmit" in str(recorded.value)


def test_markdown_joins_chunk_content_in_order_with_a_blank_line() -> None:
    chunks = parse_chunks(
        chunk_json(content="first"),
        chunk_json(content="second"),
        chunk_json(content=""),
    )
    assert build_parse_output(chunks).markdown.markdown == "first\n\nsecond\n\n"


def test_no_chunks_make_an_empty_document_in_both_artifacts() -> None:
    output = build_parse_output([])
    names = "index page original_page kind text confidence parse_confidence left"
    names += " top width height"
    assert output.markdown.markdown == ""
    assert output.blocks.rows == []
    assert [column.id for column in output.blocks.columns] == names.split()


def test_blocks_carry_the_providers_own_vocabulary() -> None:
    named = block_json(type="Handwritten Note", content="scrawled", confidence="low")
    named["granular_confidence"] = {"parse_confidence": 0.81}
    named["bbox"] = bbox_json(left=0.0, page=2)
    scored = block_json(
        content="plain", bbox=bbox_json(left=0.5, page=3, original_page=9)
    )
    later = chunk_json(content="next page", blocks=[block_json(content="later")])
    chunks = parse_chunks(chunk_json(blocks=[named, scored]), later)
    rows = build_parse_output(chunks).blocks.rows
    assert [row["index"] for row in rows] == [0, 1, 2]
    assert [row["kind"] for row in rows] == ["Handwritten Note", "Text", "Text"]
    assert [row["text"] for row in rows] == ["scrawled", "plain", "later"]
    assert [row["page"] for row in rows] == [2, 3, 1]
    # A page the provider never reported stays empty, never copied from a neighbour.
    assert [row["original_page"] for row in rows] == [None, 9, None]
    assert [row["confidence"] for row in rows] == ["low", None, None]
    assert [row["parse_confidence"] for row in rows] == [0.81, None, None]
    assert [row["left"] for row in rows] == [0.0, 0.5, 0.1]


def test_blocks_preserve_box_numbers_without_clamping_them() -> None:
    box = bbox_json(left=-0.04, top=1.28, width=1.4, height=1.05)
    chunks = parse_chunks(chunk_json(blocks=[block_json(bbox=box)]))
    row = build_parse_output(chunks).blocks.rows[0]
    assert (row["left"], row["top"], row["width"], row["height"]) == (
        -0.04,
        1.28,
        1.4,
        1.05,
    )


@pytest.mark.parametrize(
    "coordinate",
    [{"left": float("nan")}, {"top": float("inf")}, {"width": float("-inf")}],
)
def test_a_box_with_a_non_finite_coordinate_is_refused(
    coordinate: dict[str, float],
) -> None:
    with pytest.raises(ValidationError):
        parse_chunks(chunk_json(blocks=[block_json(bbox=bbox_json(**coordinate))]))


def test_a_nan_written_into_the_json_document_is_rejected_too() -> None:
    payload = json.loads(
        '{"content":"c","blocks":[{"type":"Text","content":"x",'
        '"bbox":{"left":NaN,"top":0,"width":1,"height":1,"page":1}}]}'
    )
    with pytest.raises(ValidationError):
        parse_chunks(payload)


def test_fields_no_artifact_reads_are_ignored_rather_than_modelled() -> None:
    block = block_json(image_url="https://cdn.test/1.png", chart_data=["a"])
    parsed = parse_chunks(chunk_json(blocks=[block], embed="text", enriched="text"))
    assert parsed[0].blocks[0].content == "a paragraph"


def test_a_chunk_without_its_block_array_is_a_contract_break() -> None:
    with pytest.raises(ValidationError):
        parse_chunks({"content": "no blocks here"})
