import json
import asyncio
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr, ValidationError

from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.plugins import NodeHttpEgressInput, PluginRegistry, PluginRuntimeContext
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_plugin_mistral.artifacts import OCR_DOCUMENT, OcrDocumentPayload, OcrPage
from grafy_plugin_mistral.declaration import MISTRAL
from grafy_plugin_mistral.ocr import (
    MistralOcrConfig,
    MistralOcrExecutionError,
    MistralOcrInput,
    MistralOcrNode,
    MistralOcrProviderError,
)
from grafy_plugin_mistral.ocr_sdk import MistralOcrSdkProvider
from grafy_workbench.image import IMAGES
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.text import TEXT


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000911")


class FakeNodeSecrets:
    def __init__(self, value: SecretStr) -> None:
        self._value = value
        self.dependencies: Mapping[str, JsonValue] | None = None
        self.name: str | None = None

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        del graph_id, graph_revision, node_id
        assert workspace_id == WORKSPACE_ID
        self.name = name
        self.dependencies = dependencies
        return self._value

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        return "0" * 64


class FakeProvider:
    def __init__(self, document: OcrDocumentPayload) -> None:
        self._document = document
        self.api_key: SecretStr | None = None
        self.document_url: str | None = None

    async def process(
        self,
        *,
        document_url: str | None,
        image: ArtifactRef | None,
        document_annotation_schema: str | None,
        bbox_annotation_schema: str | None,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> OcrDocumentPayload:
        del image, document_annotation_schema, bbox_annotation_schema, config
        assert workspace_id == WORKSPACE_ID
        self.document_url = document_url
        self.api_key = api_key
        return self._document


class RequestRecorder:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.next_responses: list[httpx.Response] = []
        self.requests: list[httpx.Request] = []
        self.follow_redirects: list[bool] = []
        self.closed: list[bool] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        async def send(
            client: httpx.AsyncClient,
            request: httpx.Request,
            *,
            stream: bool = False,
            auth: object = None,
            follow_redirects: object = None,
        ) -> httpx.Response:
            del stream, auth, follow_redirects
            recorder.requests.append(request)
            recorder.follow_redirects.append(client.follow_redirects)
            template = (
                recorder.next_responses.pop(0)
                if recorder.next_responses
                else recorder._response
            )
            response = httpx.Response(
                status_code=template.status_code,
                headers=template.headers,
                content=template.content,
                request=request,
            )
            return response

        monkeypatch.setattr(httpx.AsyncClient, "send", send)


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}

    async def save(self, command: SaveFileCommand) -> StoredFile:
        raise AssertionError(f"Unexpected save to {command.bucket}/{command.path}")

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        raise AssertionError(
            f"Unexpected move in {bucket}: {source_path} to {destination_path}"
        )

    async def load(self, bucket: str, path: str) -> BytesIO:
        return BytesIO(self.files[(bucket, path)])

    async def open_chunks(self, bucket: str, path: str) -> BytesIO:
        return await self.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        content = self.files.get((bucket, path))
        if content is None:
            return None
        return StoredObjectInfo(
            bucket=bucket,
            path=path,
            byte_size=len(content),
            etag=None,
            version_id=None,
        )

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        return self.files[(bucket, path)][start:end_exclusive]

    async def delete(self, bucket: str, path: str) -> None:
        raise AssertionError(f"Unexpected delete from {bucket}/{path}")


def document_payload() -> OcrDocumentPayload:
    return OcrDocumentPayload(
        markdown="# Invoice",
        pages=[
            OcrPage(
                index=0,
                markdown="# Invoice",
                images=[],
                dimensions=None,
            )
        ],
        model="mistral-ocr-latest",
        base_url="https://api.mistral.ai",
        document_kind="document_url",
        pages_processed=1,
        include_image_base64=False,
        include_blocks=True,
    )


def invoice_schema() -> str:
    return (
        '{"type":"object","properties":{"invoice_number":{"type":"string"}},'
        '"required":["invoice_number"],"additionalProperties":false}'
    )


def ocr_response(*, annotation: str | None = None) -> httpx.Response:
    body: dict[str, object] = {
        "model": "mistral-ocr-latest",
        "usage_info": {"pages_processed": 1, "doc_size_bytes": 1200},
        "pages": [
            {
                "index": 0,
                "markdown": "# Invoice\n\nTotal 10",
                "images": [
                    {
                        "id": "img-0.png",
                        "top_left_x": 1,
                        "top_left_y": 2,
                        "bottom_right_x": 30,
                        "bottom_right_y": 40,
                    }
                ],
                "dimensions": {"dpi": 200, "height": 100, "width": 80},
                "tables": [
                    {
                        "id": "tbl-0",
                        "content": "<table><tr><td>10</td></tr></table>",
                        "format": "html",
                    }
                ],
                "hyperlinks": ["https://example.com/terms"],
                "header": "Acme",
                "footer": "Page 1",
                "confidence_scores": {
                    "average_page_confidence_score": 0.9,
                    "minimum_page_confidence_score": 0.4,
                    "word_confidence_scores": [
                        {
                            "text": "Invoice",
                            "confidence": 0.99,
                            "start_index": 2,
                        }
                    ],
                },
                "blocks": [
                    {
                        "type": "text",
                        "top_left_x": 0,
                        "top_left_y": 0,
                        "bottom_right_x": 80,
                        "bottom_right_y": 20,
                        "content": "Invoice",
                    },
                    {
                        "type": "image",
                        "top_left_x": 1,
                        "top_left_y": 2,
                        "bottom_right_x": 3,
                        "bottom_right_y": 4,
                        "content": "logo",
                        "image_id": "img-0.png",
                        "confidence_scores": {
                            "average_content_confidence_score": 0.8,
                            "minimum_content_confidence_score": 0.5,
                            "block_type_confidence_score": 0.7,
                        },
                    },
                ],
            }
        ],
    }
    if annotation is not None:
        body["document_annotation"] = annotation
    return httpx.Response(200, json=body)


def test_node_declares_ocr_ports_secret_and_egress() -> None:
    assert MistralOcrNode.operator_id == "mistral.ocr.process"
    assert MistralOcrNode.operator_version == 1
    assert MistralOcrNode.plugin_slug == "external.mistral"
    assert MistralOcrNode.input_contract.ports["document_url"].accepts == (
        TEXT_VALUE.key
    )
    assert MistralOcrNode.input_contract.ports["document_url"].allows_none
    assert not MistralOcrNode.input_contract.ports["document_url"].required
    image = MistralOcrNode.input_contract.ports["image"]
    assert image.accepts == RASTER_IMAGE.key
    assert image.shape is PortShape.ONE
    assert image.allows_none
    assert MistralOcrNode.input_contract.ports[
        "document_annotation_schema"
    ].accepts == (JSON_SCHEMA.key)
    assert MistralOcrNode.output_contract.ports["document"].produces == (
        OCR_DOCUMENT.key
    )

    registration = next(
        contribution
        for contribution in MISTRAL.nodes
        if contribution.key == ("mistral.ocr.process", 1)
    )
    assert registration.secret_inputs[0].name == "api_key"
    assert registration.secret_inputs[0].config_dependencies == ("base_url",)
    assert "api_key" not in MistralOcrConfig.model_fields
    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    )
    assert registration.http_egress is not None
    assert registration.http_egress.configured_inputs == (
        NodeHttpEgressInput(config_field="base_url"),
    )


def test_config_accepts_loopback_http_and_rejects_credential_bearing_urls() -> None:
    assert (
        MistralOcrConfig(base_url="https://API.Mistral.ai/").base_url
        == "https://api.mistral.ai"
    )
    assert (
        MistralOcrConfig(base_url="http://127.0.0.1:8080").base_url
        == "http://127.0.0.1:8080"
    )
    assert MistralOcrConfig(pages="0,2-4").pages == "0,2-4"

    for base_url in (
        "http://api.example.com",
        "https://user:secret@example.com",
        "https://api.example.com?tenant=one",
        "https://api.example.com#fragment",
    ):
        with pytest.raises(ValidationError):
            MistralOcrConfig(base_url=base_url)
    with pytest.raises(ValidationError):
        MistralOcrConfig(pages="2-0")


def test_plugin_registers_ocr_document_resolution(tmp_path: Path) -> None:
    registry = PluginRegistry()
    for builtin in (IMAGES, TEXT, SCHEMAS):
        registry.install(builtin)
    registry.install(MISTRAL)
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=FakeStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )
    registry.freeze()

    document = next(
        artifact_type
        for artifact_type in registry.artifact_types
        if artifact_type.key == OCR_DOCUMENT.key
    )
    markdown = next(
        projection
        for projection in document.field_projections
        if projection.path == ("markdown",)
    )
    assert markdown.target == TEXT_VALUE.key
    assert isinstance(
        registry.build_node("mistral.ocr.process", 1, context),
        MistralOcrNode,
    )
    resolver = next(
        item
        for item in registry.build_resolvers(context)
        if item.source == OCR_DOCUMENT.key
    )
    writer = next(
        item
        for item in registry.build_writers(context)
        if item.artifact_type == OCR_DOCUMENT.key
    )
    assert isinstance(resolver, InlineModelResolver)
    assert resolver.target is OcrDocumentPayload
    assert isinstance(writer, InlineModelOutputWriter)


async def test_node_resolves_the_bound_secret_and_returns_the_document() -> None:
    secret = SecretStr("secret-provider-key")
    secrets = FakeNodeSecrets(secret)
    provider = FakeProvider(document_payload())
    node = MistralOcrNode(provider=provider, node_secrets=secrets)

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            secret_graph_id=uuid4(),
            secret_graph_revision=2,
            node_id="ocr-1",
        ),
        MistralOcrConfig(),
        MistralOcrInput(document_url="https://files.example/report.pdf"),
    )

    assert secrets.name == "api_key"
    assert secrets.dependencies == {"base_url": "https://api.mistral.ai"}
    assert provider.api_key == secret
    assert output.document.markdown == "# Invoice"


async def test_node_requires_exactly_one_document_source() -> None:
    node = MistralOcrNode(
        provider=FakeProvider(document_payload()),
        node_secrets=FakeNodeSecrets(SecretStr("secret-provider-key")),
    )
    context = NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="ocr-1")

    with pytest.raises(MistralOcrExecutionError, match="exactly one"):
        await node.run(context, MistralOcrConfig(), MistralOcrInput())
    with pytest.raises(MistralOcrExecutionError, match="exactly one"):
        await node.run(
            context,
            MistralOcrConfig(),
            MistralOcrInput(
                document_url="https://files.example/report.pdf",
                image=ArtifactRef.from_key(
                    artifact_id=uuid4(),
                    key=RASTER_IMAGE.key,
                ),
            ),
        )


async def test_provider_posts_the_ocr_process_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(ocr_response(annotation='{"invoice_number":"A-1"}'))
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(
        uow=InMemoryUnitOfWork(),
        storage=FakeStorage(),
    )
    schema = invoice_schema()

    document = await provider.process(
        document_url="https://files.example/report.pdf?token=abc",
        image=None,
        document_annotation_schema=schema,
        bbox_annotation_schema=None,
        config=MistralOcrConfig(
            base_url="https://api.mistral.ai/",
            model="mistral-ocr-latest",
            document_name="report.pdf",
            pages="0-1",
            image_limit=2,
            image_min_size=10,
            table_format="html",
            extract_header=True,
            extract_footer=True,
            confidence_scores_granularity="page",
            document_annotation_prompt="Extract the invoice number.",
            timeout_ms=30_000,
        ),
        api_key=SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    assert recorder.follow_redirects == [False]
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert str(request.url) == "https://api.mistral.ai/v1/ocr"
    assert request.headers["authorization"] == "Bearer secret-provider-key"
    assert json.loads(request.content) == {
        "model": "mistral-ocr-latest",
        "document": {
            "document_name": "report.pdf",
            "document_url": "https://files.example/report.pdf?token=abc",
            "type": "document_url",
        },
        "pages": "0-1",
        "include_image_base64": False,
        "image_limit": 2,
        "image_min_size": 10,
        "document_annotation_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "document_annotation",
                "schema": {
                    "type": "object",
                    "properties": {"invoice_number": {"type": "string"}},
                    "required": ["invoice_number"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        },
        "document_annotation_prompt": "Extract the invoice number.",
        "table_format": "html",
        "extract_header": True,
        "extract_footer": True,
        "include_blocks": True,
        "confidence_scores_granularity": "page",
    }
    assert document.markdown == "# Invoice\n\nTotal 10"
    assert document.document_kind == "document_url"
    assert document.pages_processed == 1
    assert document.doc_size_bytes == 1200
    assert document.document_annotation == {"invoice_number": "A-1"}
    assert document.table_format == "html"
    page = document.pages[0]
    assert page.header == "Acme"
    assert page.footer == "Page 1"
    assert page.tables[0].format == "html"
    assert page.hyperlinks == ["https://example.com/terms"]
    assert page.confidence_scores is not None
    assert page.confidence_scores.word_confidence_scores[0].text == "Invoice"
    assert page.blocks is not None
    assert page.blocks[0].type == "text"
    image_block = page.blocks[1]
    assert image_block.type == "image"
    assert image_block.image_id == "img-0.png"
    assert "secret-provider-key" not in document.model_dump_json()


async def test_provider_sends_a_raster_image_as_a_data_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(ocr_response())
    recorder.install(monkeypatch)
    uow = InMemoryUnitOfWork()
    storage = FakeStorage()
    content = b"\x89PNG\r\n\x1a\nfake"
    image = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=uuid4(),
        artifact_type=RASTER_IMAGE.key.id,
        schema_version=RASTER_IMAGE.key.schema_version,
        content_type="image/png",
        bucket="artifacts",
        object_key="images/page.png",
        byte_size=len(content),
    )
    storage.files[("artifacts", "images/page.png")] = content
    async with uow as transaction:
        await transaction.artifacts.add(image)
        await transaction.commit()
    provider = MistralOcrSdkProvider(uow=uow, storage=storage)

    document = await provider.process(
        document_url=None,
        image=image.ref(),
        document_annotation_schema=None,
        bbox_annotation_schema=None,
        config=MistralOcrConfig(include_blocks=False),
        api_key=SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    body = cast(dict[str, object], json.loads(recorder.requests[0].content))
    sent = cast(dict[str, object], body["document"])
    assert sent["type"] == "image_url"
    assert sent["image_url"] == ("data:image/png;base64,iVBORw0KGgpmYWtl")
    assert body["include_blocks"] is False
    assert document.document_kind == "image_url"
    assert document.source_image_artifact_id == image.id
    assert document.pages[0].blocks is None


async def test_provider_hides_rejected_response_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(
        httpx.Response(
            401,
            json={"detail": "secret-provider-key"},
        )
    )
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(
        uow=InMemoryUnitOfWork(),
        storage=FakeStorage(),
    )

    with pytest.raises(MistralOcrProviderError, match="HTTP 401") as raised:
        await provider.process(
            document_url="https://files.example/report.pdf",
            image=None,
            document_annotation_schema=None,
            bbox_annotation_schema=None,
            config=MistralOcrConfig(),
            api_key=SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert "secret-provider-key" not in str(raised.value)


@pytest.mark.parametrize("pages", ["", "2-1", "-1", "0,", " 0", "1.5", "1--2"])
def test_config_rejects_invalid_page_selection(pages: str) -> None:
    with pytest.raises(ValidationError, match="pages"):
        _ = MistralOcrConfig(pages=pages)


@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500])
async def test_provider_retries_only_retryable_statuses_when_enabled(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    recorder = RequestRecorder(ocr_response())
    error_body: dict[str, object] = {"detail": "private-body"}
    if status == 422:
        error_body = {
            "detail": [{"loc": ["body"], "msg": "private-body", "type": "value_error"}]
        }
    recorder.next_responses = [httpx.Response(status, json=error_body)]
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    if status in {429, 500}:
        document = await provider.process(
            document_url="https://files.example/report.pdf",
            image=None,
            document_annotation_schema=None,
            bbox_annotation_schema=None,
            config=MistralOcrConfig(max_retries=1),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )
        assert document.pages_processed == 1
        assert len(recorder.requests) == 2
    else:
        with pytest.raises(MistralOcrProviderError, match=f"HTTP {status}") as raised:
            _ = await provider.process(
                document_url="https://files.example/report.pdf",
                image=None,
                document_annotation_schema=None,
                bbox_annotation_schema=None,
                config=MistralOcrConfig(max_retries=1),
                api_key=SecretStr("key"),
                workspace_id=WORKSPACE_ID,
            )
        assert "private-body" not in str(raised.value)
        assert len(recorder.requests) == 1


@pytest.mark.parametrize("annotation", [None, "not-json", "[]", '{"wrong":"private"}'])
async def test_provider_rejects_invalid_document_annotations(
    monkeypatch: pytest.MonkeyPatch, annotation: str | None
) -> None:
    recorder = RequestRecorder(ocr_response(annotation=annotation))
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    with pytest.raises(MistralOcrProviderError, match="expected schema") as raised:
        _ = await provider.process(
            document_url="https://files.example/report.pdf",
            image=None,
            document_annotation_schema=invoice_schema(),
            bbox_annotation_schema=None,
            config=MistralOcrConfig(),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )
    assert "private" not in str(raised.value)


async def test_provider_accepts_minimal_response_and_absent_usage_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(
        httpx.Response(
            200,
            json={
                "model": "mistral-ocr-latest",
                "usage_info": {"pages_processed": 1},
                "pages": [
                    {"index": 0, "markdown": "Text", "images": [], "dimensions": None}
                ],
            },
        )
    )
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    document = await provider.process(
        document_url="https://files.example/report.pdf",
        image=None,
        document_annotation_schema=None,
        bbox_annotation_schema=None,
        config=MistralOcrConfig(),
        api_key=SecretStr("key"),
        workspace_id=WORKSPACE_ID,
    )
    assert document.doc_size_bytes is None
    assert document.pages[0].tables == []
    assert document.pages[0].blocks is None
    assert document.markdown == "Text"
    assert "document_annotation_format" not in json.loads(recorder.requests[0].content)


async def test_provider_preserves_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def send(
        client: httpx.AsyncClient,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: object = None,
        follow_redirects: object = None,
    ) -> httpx.Response:
        del client, request, stream, auth, follow_redirects
        raise asyncio.CancelledError

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    with pytest.raises(asyncio.CancelledError):
        _ = await provider.process(
            document_url="https://files.example/report.pdf",
            image=None,
            document_annotation_schema=None,
            bbox_annotation_schema=None,
            config=MistralOcrConfig(max_retries=1),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.parametrize("include_images", [False, True])
async def test_provider_preserves_image_annotations_and_table_word_scores(
    monkeypatch: pytest.MonkeyPatch, include_images: bool
) -> None:
    body = cast(dict[str, object], ocr_response().json())
    pages = cast(list[dict[str, object]], body["pages"])
    page = pages[0]
    images = cast(list[dict[str, object]], page["images"])
    images[0]["image_annotation"] = '{"invoice_number":"image-A"}'
    images[0]["image_base64"] = "aGVsbG8="
    tables = cast(list[dict[str, object]], page["tables"])
    tables[0]["word_confidence_scores"] = [
        {"text": "10", "confidence": 0.95, "start_index": 19}
    ]
    recorder = RequestRecorder(httpx.Response(200, json=body))
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    document = await provider.process(
        document_url="https://files.example/report.pdf?token=source-secret",
        image=None,
        document_annotation_schema=None,
        bbox_annotation_schema=invoice_schema(),
        config=MistralOcrConfig(include_image_base64=include_images),
        api_key=SecretStr("provider-secret"),
        workspace_id=WORKSPACE_ID,
    )
    image = document.pages[0].images[0]
    assert image.image_annotation == {"invoice_number": "image-A"}
    assert image.image_base64 == ("aGVsbG8=" if include_images else None)
    assert document.pages[0].tables[0].word_confidence_scores[0].text == "10"
    assert document.pages[0].tables[0].word_confidence_scores[0].confidence == 0.95
    saved = document.model_dump_json()
    assert "provider-secret" not in saved
    assert "source-secret" not in saved
    request = cast(dict[str, object], json.loads(recorder.requests[0].content))
    bbox_format = cast(dict[str, object], request["bbox_annotation_format"])
    assert bbox_format["type"] == "json_schema"
    assert document == OcrDocumentPayload.model_validate_json(saved)
