import asyncio
import json
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from grafy_core.contracts.ocr import DocumentOcrResult
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import NodeExecutionContext, bind_node_secrets
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_plugin_mistral import ocr_sdk
from grafy_plugin_mistral.declaration import MISTRAL
from grafy_plugin_mistral.ocr import (
    API_KEY,
    MistralOcrConfig,
    MistralProviderInput,
    MistralOcrProviderNode,
    MistralOcrProviderError,
    build_ocr_output,
)
from grafy_plugin_mistral.ocr_sdk import MistralOcrSdkProvider
from mistralai.client.models.ocrresponse import OCRResponse
from pydantic import SecretStr, ValidationError

from tests.support.egress import (
    loopback_http_listener,
    no_grants,
    trusted_loopback_destination,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000911")


def pdf_document() -> PdfFile:
    return PdfFile.from_content(
        b"%PDF-example", content_type="application/pdf", filename="report.pdf"
    )


class FakeNodeSecrets:
    def __init__(self, value: SecretStr) -> None:
        self._value = value
        self.dependencies: Mapping[str, JsonValue] | None = None
        self.name: str | None = None

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
        del graph_id, node_id, project_id
        assert workspace_id == WORKSPACE_ID
        self.name = name
        self.dependencies = dependencies
        return self._value

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
        del workspace_id, project_id, graph_id, node_id, name, dependencies
        return "0" * 64


class FakeProvider:
    def __init__(self, document: DocumentOcrResult) -> None:
        self._document = document
        self.api_key: SecretStr | None = None

    async def process(
        self,
        *,
        image: RasterImage | PdfFile,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> DocumentOcrResult:
        del image, config
        assert workspace_id == WORKSPACE_ID
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


def document_payload() -> DocumentOcrResult:
    return build_ocr_output(
        OCRResponse.model_validate(ocr_response().json()), MistralOcrConfig()
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
    assert MistralOcrProviderNode.operator_id == "mistral.ocr.provider"
    assert MistralOcrProviderNode.operator_version == 1
    assert MistralOcrProviderNode.plugin_slug == "external.mistral"
    assert not MistralOcrProviderNode.input_contract.ports
    engine = MistralOcrProviderNode.output_contract.ports["engine"]
    assert engine.kind == "service"

    registration = next(
        contribution
        for contribution in MISTRAL.nodes
        if contribution.key == ("mistral.ocr.provider", 1)
    )
    assert registration.secret_inputs[0].name == "api_key"
    assert registration.secret_inputs[0].provider_kind == "mistral"
    assert registration.secret_inputs[0].config_dependencies == ()
    assert "api_key" not in MistralOcrConfig.model_fields
    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    )
    assert registration.http_egress is not None
    assert registration.http_egress.fixed_destinations == ("https://api.mistral.ai",)
    assert registration.http_egress.configured_inputs == ()
    assert not registration.http_egress.dynamic_destinations


def test_config_rejects_the_retired_provider_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MistralOcrConfig.model_validate(
            {"base_url": "https://api.mistral.ai/v1", "model": "mistral-ocr-latest"}
        )


def test_plugin_builds_the_registered_provider(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.install(MISTRAL)
    registry.freeze()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=FakeStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )
    assert MISTRAL.artifacts == ()
    assert registry.declared_artifact_types == ()
    assert isinstance(
        registry.build_node("mistral.ocr.provider", 1, context), MistralOcrProviderNode
    )


async def test_provider_resolves_the_bound_secret_and_reads_the_document() -> None:
    secret = SecretStr("secret-provider-key")
    secrets = FakeNodeSecrets(secret)
    provider = FakeProvider(document_payload())
    node = MistralOcrProviderNode(provider=provider)

    output = await node.run(
        bind_node_secrets(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                project_id=uuid4(),
                graph_id="scans",
                node_id="ocr-1",
            ),
            secrets,
            (API_KEY,),
        ),
        MistralOcrConfig(),
        MistralProviderInput(),
    )

    document = await output.engine.read(pdf_document())

    assert secrets.name == "api_key"
    assert secrets.dependencies == {}
    assert provider.api_key == secret
    assert document.markdown.markdown == "# Invoice\n\nTotal 10"


async def test_provider_posts_the_ocr_process_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(ocr_response())
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider()
    output = await provider.process(
        image=pdf_document(),
        config=MistralOcrConfig(
            table_format="html",
            extract_header=True,
            extract_footer=True,
            confidence_scores_granularity="page",
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
            "document_url": "data:application/pdf;base64,JVBERi1leGFtcGxl",
            "type": "document_url",
        },
        "include_image_base64": False,
        "include_blocks": True,
        "table_format": "html",
        "extract_header": True,
        "extract_footer": True,
        "confidence_scores_granularity": "page",
    }
    assert output.markdown.markdown == "# Invoice\n\nTotal 10"
    assert output.blocks is not None
    assert output.blocks.rows[0]["page_confidence"] == 0.9


async def test_provider_sends_a_raster_image_as_a_data_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(ocr_response())
    recorder.install(monkeypatch)
    content = b"\x89PNG\r\n\x1a\nfake"
    image = RasterImage.from_content(
        content, content_type="image/png", filename="page.png"
    )
    provider = MistralOcrSdkProvider()

    document = await provider.process(
        image=image,
        config=MistralOcrConfig(),
        api_key=SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    body = cast(dict[str, object], json.loads(recorder.requests[0].content))
    sent = cast(dict[str, object], body["document"])
    assert sent["type"] == "image_url"
    assert sent["image_url"] == ("data:image/png;base64,iVBORw0KGgpmYWtl")
    assert body["include_blocks"] is True
    assert document.regions is not None
    assert document.regions.pages[0].index == 0


async def test_provider_sends_pdf_as_document_data_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(ocr_response())
    recorder.install(monkeypatch)
    content = b"%PDF-example"
    pdf = PdfFile.from_content(
        content, content_type="application/pdf", filename="page.pdf"
    )
    provider = MistralOcrSdkProvider()
    await provider.process(
        image=pdf,
        config=MistralOcrConfig(),
        api_key=SecretStr("key"),
        workspace_id=WORKSPACE_ID,
    )
    body = cast(dict[str, object], json.loads(recorder.requests[0].content))
    assert body["document"] == {
        "type": "document_url",
        "document_url": "data:application/pdf;base64,JVBERi1leGFtcGxl",
    }


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
    provider = MistralOcrSdkProvider()

    with pytest.raises(MistralOcrProviderError, match="HTTP 401") as raised:
        await provider.process(
            image=pdf_document(),
            config=MistralOcrConfig(),
            api_key=SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert "secret-provider-key" not in str(raised.value)


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
    provider = MistralOcrSdkProvider()
    if status in {429, 500}:
        document = await provider.process(
            image=pdf_document(),
            config=MistralOcrConfig(max_retries=1),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )
        assert document.regions is not None
        assert len(document.regions.pages) == 1
        assert len(recorder.requests) == 2
    else:
        with pytest.raises(MistralOcrProviderError, match=f"HTTP {status}") as raised:
            _ = await provider.process(
                image=pdf_document(),
                config=MistralOcrConfig(max_retries=1),
                api_key=SecretStr("key"),
                workspace_id=WORKSPACE_ID,
            )
        assert "private-body" not in str(raised.value)
        assert len(recorder.requests) == 1


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
    provider = MistralOcrSdkProvider()
    with pytest.raises(asyncio.CancelledError):
        _ = await provider.process(
            image=pdf_document(),
            config=MistralOcrConfig(max_retries=1),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )


async def test_provider_dials_a_self_hosted_endpoint_only_when_the_operator_allows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider endpoint is dialable only through the deployment policy.

    A Mistral-compatible server kept on the local network is reached with the grant
    an operator writes for it. Without the grant the request is refused before a
    socket opens, so the listener never sees it.
    """

    monkeypatch.setattr(ocr_sdk, "MISTRAL_API_BASE_URL", "http://127.0.0.1:1")
    async with loopback_http_listener(body=ocr_response().content) as listener:
        monkeypatch.setattr(ocr_sdk, "MISTRAL_API_BASE_URL", listener.base_url)
        config = MistralOcrConfig(timeout_ms=5_000, max_retries=0)

        async def process(egress_policy: object) -> str:
            provider = MistralOcrSdkProvider(
                egress_policy=egress_policy,  # pyright: ignore[reportArgumentType]
            )
            output = await provider.process(
                image=pdf_document(),
                config=config,
                api_key=SecretStr("secret-provider-key"),
                workspace_id=WORKSPACE_ID,
            )
            return output.markdown.markdown

        assert await process(trusted_loopback_destination()) == "# Invoice\n\nTotal 10"
        assert [request.path for request in listener.requests] == ["/v1/ocr"]

        # A destination this deployment refuses says so as itself, instead of
        # arriving as a connection failure the provider would also cause.
        with pytest.raises(
            MistralOcrProviderError, match="may not be dialed"
        ) as raised:
            await process(no_grants())

        assert "127.0.0.1" in str(raised.value)
        assert len(listener.requests) == 1
