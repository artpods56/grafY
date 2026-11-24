"""Live progress from the OCR and LLM nodes that used to show only "Running…"."""

import json
from dataclasses import replace
from io import BytesIO
from typing import ClassVar, cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from mistralai.client.models.ocrresponse import OCRResponse
from PIL import Image
from pydantic import SecretStr

from grafy_api.realtime.hub import ProjectRoomHub
from grafy_api.realtime.protocol import NodeProgressMessage
from grafy_api.realtime.run_events import ProjectNodeProgress
from grafy_core.artifact_contracts import (
    ImagePage,
    ImageRegion,
    ImageRegionSet,
    MarkdownValue,
    RASTER_IMAGE,
)
from grafy_core.artifacts import ArtifactRef
from grafy_core.contracts.ocr import DocumentOcr, DocumentOcrFeature, DocumentOcrResult
from grafy_core.documents import CsvFile, PdfFile, RasterImage
from grafy_core.node_context import NodeExecutionContext
from grafy_core.nodes import active_node_context, bind_active_node, emit_node_progress
from grafy_core.prompt_contracts import PromptMessage, PromptMessageRole
from grafy_core.provider_http import ProviderRequest
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_plugin_image.nodes import (
    CropRegionsConfig,
    CropRegionsInput,
    CropRegionsNode,
)
from grafy_plugin_litellm_ocr.craft import CRAFT_MODEL, CraftDetector
from grafy_plugin_litellm_ocr.paddle_recognizer import (
    PADDLE_MODEL,
    PaddleCyrillicRecognizer,
)
from grafy_plugin_llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleInput,
    OpenAICompatibleNode,
    OpenAICompatibleProviderResponse,
)
from grafy_plugin_mistral.ocr import MistralOcrConfig, assemble_ocr_output
from grafy_plugin_table.nodes import (
    ImportTableNode,
    TableImportConfig,
    TableImportInput,
)
from grafy_workbench.ocr.nodes import OcrConfig, OcrInput, OcrNode
from grafy_workbench.table.concat import (
    ConcatTablesConfig,
    ConcatTablesInput,
    ConcatTablesNode,
)
from grafy_workbench.table.markdown_tables import (
    ExtractMarkdownTablesConfig,
    ExtractMarkdownTablesInput,
    ExtractMarkdownTablesNode,
)

HEADER_LIMIT = 42
ProgressEvent = tuple[str, int | None, int | None]


class Reporter:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context
        self.events.append((message, current, total))


class RecordingHub:
    def __init__(self) -> None:
        self.messages: list[NodeProgressMessage] = []

    async def publish_transient(
        self,
        *,
        workspace_id: object,
        project_id: object,
        message: NodeProgressMessage,
    ) -> None:
        del workspace_id, project_id
        self.messages.append(message)


def context_for(reporter: Reporter) -> NodeExecutionContext:
    return NodeExecutionContext(
        workspace_id=uuid4(),
        project_id=uuid4(),
        graph_id="drafts",
        node_id="node-1",
        fingerprint="fp-1",
        progress_reporter=reporter,
    )


def messages_of(reporter: Reporter) -> list[str]:
    assert all(len(message) <= HEADER_LIMIT for message, _, _ in reporter.events)
    return [message for message, _, _ in reporter.events]


def ocr_page(index: int, markdown: str) -> dict[str, object]:
    return {
        "index": index,
        "markdown": markdown,
        "images": [],
        "dimensions": {"dpi": 200, "height": 100, "width": 80},
    }


def ocr_response(*pages: dict[str, object]) -> OCRResponse:
    return OCRResponse.model_validate(
        {
            "model": "mistral-ocr-latest",
            "usage_info": {"pages_processed": len(pages), "doc_size_bytes": 1200},
            "pages": list(pages),
        }
    )


def png_image() -> RasterImage:
    output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    return RasterImage.from_content(
        output.getvalue(), content_type="image/png", filename="page.png"
    )


def text_table(name: str) -> Table:
    return Table(
        columns=[TableColumn(id="name", title="Name", value_type=TableValueType.TEXT)],
        rows=[{"name": name}],
    )


class TalkingReader(DocumentOcr):
    features: ClassVar[frozenset[DocumentOcrFeature]] = frozenset()

    def __init__(self) -> None:
        self.seen: NodeExecutionContext | None = None

    async def read(self, document: object) -> DocumentOcrResult:
        del document
        self.seen = active_node_context()
        await emit_node_progress(self.seen, "Calling engine…")
        return DocumentOcrResult(markdown=MarkdownValue(markdown="read"))


class SyncProgress:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def progress(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        del current, total
        self.messages.append(message)


class ChatProvider:
    async def complete(
        self,
        messages: list[PromptMessage],
        json_schema: str | None,
        config: OpenAICompatibleConfig,
        api_key: SecretStr,
        /,
        *,
        workspace_id: UUID,
    ) -> OpenAICompatibleProviderResponse:
        del messages, json_schema, config, api_key, workspace_id
        return OpenAICompatibleProviderResponse(content="done", model="m")


class ChatSecrets:
    async def resolve_secret(self, **_kwargs: object) -> SecretStr:
        return SecretStr("secret-provider-key")

    async def cache_revision(self, **_kwargs: object) -> str:
        return "0" * 64


def chat_node() -> OpenAICompatibleNode:
    return OpenAICompatibleNode(
        provider=ChatProvider(),
        node_secrets=ChatSecrets(),
    )


async def test_emit_is_a_no_op_without_a_reporter() -> None:
    await emit_node_progress(None, "Calling LLM…")
    await emit_node_progress(object(), "Calling LLM…")
    await emit_node_progress(MagicMock(), "Calling LLM…")
    sync = SyncProgress()
    await emit_node_progress(sync, "Parsing response…", current=1, total=2)
    assert sync.messages == ["Parsing response…"]


async def test_document_ocr_reports_on_the_card_that_is_reading() -> None:
    reporter = Reporter()
    context = context_for(reporter)
    reader = TalkingReader()
    document = PdfFile.from_content(
        b"%PDF-1.4", content_type="application/pdf", filename="page.pdf"
    )

    output = await OcrNode().run(
        context,
        OcrConfig(),
        OcrInput(document=document, engine=reader),
    )

    assert output.markdown.markdown == "read"
    assert reader.seen is context
    assert active_node_context() is None
    assert messages_of(reporter) == ["Reading document…", "Calling engine…"]


async def test_mistral_assembly_counts_pages() -> None:
    reporter = Reporter()
    response = ocr_response(ocr_page(0, "one"), ocr_page(1, "two"))
    async with bind_active_node(context_for(reporter)):
        assembled = await assemble_ocr_output(response, MistralOcrConfig())

    quiet = await assemble_ocr_output(response, MistralOcrConfig())

    assert assembled.markdown.markdown == "one\n\ntwo"
    assert quiet.markdown.markdown == assembled.markdown.markdown
    assert messages_of(reporter) == [
        "Parsing OCR layout…",
        "Processing page 1 of 2",
        "Processing page 2 of 2",
    ]
    assert reporter.events[1][1:] == (1, 2)
    assert reporter.events[2][1:] == (2, 2)


async def test_chat_completion_reports_the_call_and_image_preparation() -> None:
    reporter = Reporter()
    context = context_for(reporter)
    node = chat_node()
    await node.run(
        context,
        OpenAICompatibleConfig(),
        OpenAICompatibleInput(
            messages=[
                PromptMessage(role=PromptMessageRole.USER, text="Hello"),
            ]
        ),
    )
    assert messages_of(reporter) == ["Calling LLM…", "Parsing response…"]

    with_images = Reporter()
    await node.run(
        context_for(with_images),
        OpenAICompatibleConfig(),
        OpenAICompatibleInput(
            messages=[
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Look",
                    image_refs=[
                        ArtifactRef.from_key(artifact_id=uuid4(), key=RASTER_IMAGE.key),
                        ArtifactRef.from_key(artifact_id=uuid4(), key=RASTER_IMAGE.key),
                    ],
                )
            ]
        ),
    )
    assert messages_of(with_images) == [
        "Preparing images…",
        "Calling LLM…",
        "Parsing response…",
    ]
    assert with_images.events[0][1:] == (0, 2)


async def test_extract_and_stack_count_each_table() -> None:
    reporter = Reporter()
    markdown = (
        "<table><tr><td>a</td><td>b</td></tr></table>\n"
        "<table><tr><td>c</td><td>d</td></tr></table>"
    )
    await ExtractMarkdownTablesNode().run(
        context_for(reporter),
        ExtractMarkdownTablesConfig(),
        ExtractMarkdownTablesInput(markdown=MarkdownValue(markdown=markdown)),
    )
    assert messages_of(reporter) == [
        "Extracting tables…",
        "Extracting table 1 of 2",
        "Extracting table 2 of 2",
    ]
    assert reporter.events[1][1:] == (1, 2)
    assert reporter.events[2][1:] == (2, 2)

    stacking = Reporter()
    await ConcatTablesNode().run(
        context_for(stacking),
        ConcatTablesConfig(),
        ConcatTablesInput(tables=[text_table("a"), text_table("b")]),
    )
    assert messages_of(stacking) == [
        "Stacking tables…",
        "Stacking table 1 of 2",
        "Stacking table 2 of 2",
    ]
    assert stacking.events[0][1:] == (0, 2)
    assert stacking.events[2][1:] == (2, 2)


async def test_spreadsheet_import_reports_the_read() -> None:
    reporter = Reporter()
    spreadsheet = CsvFile.from_content(
        b"name,score\nAlpha,1\n",
        content_type="text/csv",
        filename="scores.csv",
    )
    output = await ImportTableNode().run(
        context_for(reporter),
        TableImportConfig(),
        TableImportInput(file=spreadsheet),
    )
    assert output.table.rows[0]["column_1"] == "Alpha"
    assert messages_of(reporter) == ["Reading spreadsheet…"]


async def test_cropping_counts_each_region() -> None:
    reporter = Reporter()
    regions = ImageRegionSet(
        pages=[ImagePage(index=0, width=20, height=20)],
        regions=[
            ImageRegion(page=0, x0=0, y0=0, x1=8, y1=8, kind="image"),
            ImageRegion(page=0, x0=8, y0=8, x1=16, y1=16, kind="image"),
        ],
    )
    output = await CropRegionsNode().run(
        context_for(reporter),
        CropRegionsConfig(),
        CropRegionsInput(image=png_image(), regions=regions),
    )
    assert len(output.crops) == 2
    assert messages_of(reporter) == [
        "Cropping region 1 of 2",
        "Cropping region 2 of 2",
    ]
    assert reporter.events[0][1:] == (1, 2)
    assert reporter.events[1][1:] == (2, 2)


async def test_craft_and_paddle_report_the_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def craft_post(request: ProviderRequest) -> bytes:
        del request
        return json.dumps(
            {
                "width": 8,
                "height": 8,
                "model": CRAFT_MODEL,
                "polygons": [[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0]]],
            }
        ).encode()

    async def paddle_post(request: ProviderRequest) -> bytes:
        images: list[str] = request.payload["images_base64"]
        assert images
        return json.dumps(
            {
                "results": [
                    {"text": "а", "confidence": 0.9, "model": PADDLE_MODEL}
                    for _ in images
                ]
            }
        ).encode()

    monkeypatch.setattr("grafy_plugin_litellm_ocr.craft.post_json", craft_post)
    monkeypatch.setattr(
        "grafy_plugin_litellm_ocr.paddle_recognizer.post_json", paddle_post
    )

    reporter = Reporter()
    context = context_for(reporter)
    detector = CraftDetector(
        SecretStr("scoped-test"),
        timeout_ms=1_000,
        max_retries=0,
        text_threshold=0.7,
        link_threshold=0.4,
        low_text=0.4,
    )
    quiet = await detector.detect(b"png", width=8, height=8)
    async with bind_active_node(context):
        found = await detector.detect(b"png", width=8, height=8)
    assert len(quiet) == 1
    assert len(found) == 1
    assert messages_of(reporter) == ["Calling CRAFT…"]

    paddle = Reporter()
    recognizer = PaddleCyrillicRecognizer(
        SecretStr("scoped-test"), timeout_ms=1_000, max_retries=0
    )
    async with bind_active_node(context_for(paddle)):
        readings = await recognizer.recognize([b"crop"] * 9)
    assert len(readings) == 9
    assert messages_of(paddle) == ["Calling Cyrillic OCR…"] * 3
    assert [event[1:] for event in paddle.events] == [(0, 9), (8, 9), (9, 9)]

    empty = Reporter()
    async with bind_active_node(context_for(empty)):
        assert await recognizer.recognize([]) == []
    assert empty.events == []


async def test_project_progress_publishes_normal_and_mapped_nodes() -> None:
    hub = RecordingHub()
    progress = ProjectNodeProgress(cast(ProjectRoomHub, hub))
    workspace_id = uuid4()
    project_id = uuid4()
    context = NodeExecutionContext(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="graph-1",
        node_id="ocr-1",
        call_path=("cell",),
        fingerprint="fp-1",
    )

    await progress.report_progress(context, "Calling LLM…", current=None, total=None)
    await progress.report_progress(
        replace(context, invocation_index=1, invocation_path=(1,)),
        "Processing page 2 of 5",
        current=2,
        total=5,
    )
    await progress.report_progress(
        replace(context, fingerprint=None),
        "Calling LLM…",
        current=None,
        total=None,
    )

    assert len(hub.messages) == 2
    first = hub.messages[0]
    assert first.sequence == 1
    assert first.instance.map_index is None
    assert first.instance.node_id == "ocr-1"
    assert first.instance.call_path == ("cell",)
    dumped = first.model_dump(mode="json")
    assert dumped["current"] is None
    assert dumped["total"] is None
    assert dumped["invocation_path"] == []
    assert dumped["instance"]["map_index"] is None
    assert dumped["type"] == "node.progress"

    second = hub.messages[1]
    assert second.sequence == 2
    assert second.instance.map_index is None
    assert second.invocation_path == (1,)
    assert second.current == 2
    assert second.total == 5
    assert second.model_dump(mode="json")["invocation_path"] == [1]
