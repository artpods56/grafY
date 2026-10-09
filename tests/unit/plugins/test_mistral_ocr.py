from hashlib import sha256
import json
import asyncio
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from grafy_core.artifact_contracts import (
    RASTER_IMAGE,
    TEXT_VALUE,
    MARKDOWN,
    IMAGE_REGIONS,
)
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_plugin_mistral.declaration import MISTRAL
from grafy_plugin_mistral.ocr import (
    MistralOcrConfig,
    MistralOcrOutput,
    MistralOcrExecutionError,
    MistralOcrInput,
    MistralOcrNode,
    MistralOcrProviderError,
)
from grafy_plugin_mistral.ocr_sdk import MistralOcrSdkProvider
from grafy_core.domain.node_secrets import node_secret_dependency_sha256
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeKey,
    PluginCatalogManifest,
    PluginReleaseScope,
    plugin_contract_digest,
    plugin_protocol_digest,
)
from grafy_core.runtime.plugin_guest import execute_plugin_invocation
from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest
from grafy_core.runtime.plugin_protocol import (
    PluginInputArtifactBundle,
    PluginInputArtifactGroup,
    PluginInputBinding,
    PluginInvocationEnvelope,
    PluginInvocationLimits,
    PluginInvocationRelease,
    PluginInvocationResultEnvelope,
    PluginOutputDeclaration,
    PluginSecretBinding,
)
from grafy_core.runtime.table_bundle import load_table_bundle
from grafy_core.table_contracts import TABLE_DATA
from mistralai.client.models.ocrresponse import OCRResponse
from grafy_plugin_mistral.ocr import build_ocr_output


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
    def __init__(self, document: MistralOcrOutput) -> None:
        self._document = document
        self.api_key: SecretStr | None = None
        self.document_url: str | None = None

    async def process(
        self,
        *,
        document_url: str | None,
        image: ArtifactRef | None,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> MistralOcrOutput:
        del image, config
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


def document_payload() -> MistralOcrOutput:
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
    assert set(MistralOcrNode.input_contract.ports) == {"document_url", "image"}
    assert {
        name: port.produces
        for name, port in MistralOcrNode.output_contract.ports.items()
    } == {
        "markdown": MARKDOWN.key,
        "blocks": TABLE_DATA.key,
        "regions": IMAGE_REGIONS.key,
        "figures": RASTER_IMAGE.key,
    }

    registration = next(
        contribution
        for contribution in MISTRAL.nodes
        if contribution.key == ("mistral.ocr.process", 1)
    )
    assert registration.secret_inputs[0].name == "api_key"
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


def test_plugin_registers_dependency_writers(tmp_path: Path) -> None:
    registry = PluginRegistry()
    registry.install(MISTRAL)
    registry.freeze()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=FakeStorage(),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )
    writers = {
        writer.artifact_type: writer for writer in registry.build_writers(context)
    }
    assert set(writers) == {MARKDOWN.key, IMAGE_REGIONS.key, RASTER_IMAGE.key}
    assert isinstance(writers[MARKDOWN.key], InlineModelOutputWriter)
    # TABLE_DATA uses the guest's table-bundle fallback, like the SQL plugin.
    assert TABLE_DATA.key in {spec.key for spec in MISTRAL.artifact_type_dependencies}
    assert registry.declared_artifact_types == ()
    assert isinstance(
        registry.build_node("mistral.ocr.process", 1, context), MistralOcrNode
    )


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
    assert secrets.dependencies == {}
    assert provider.api_key == secret
    assert output.markdown.markdown == "# Invoice\n\nTotal 10"


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
    recorder = RequestRecorder(ocr_response())
    recorder.install(monkeypatch)
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    output = await provider.process(
        document_url="https://files.example/report.pdf?token=abc",
        image=None,
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
            "document_url": "https://files.example/report.pdf?token=abc",
            "type": "document_url",
        },
        "include_image_base64": True,
        "include_blocks": True,
        "table_format": "html",
        "extract_header": True,
        "extract_footer": True,
        "confidence_scores_granularity": "page",
    }
    assert output.markdown.markdown == "# Invoice\n\nTotal 10"
    assert output.blocks.rows[0]["page_confidence"] == 0.9


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
        config=MistralOcrConfig(),
        api_key=SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    body = cast(dict[str, object], json.loads(recorder.requests[0].content))
    sent = cast(dict[str, object], body["document"])
    assert sent["type"] == "image_url"
    assert sent["image_url"] == ("data:image/png;base64,iVBORw0KGgpmYWtl")
    assert body["include_blocks"] is True
    assert document.regions[0].page_index == 0


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
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    if status in {429, 500}:
        document = await provider.process(
            document_url="https://files.example/report.pdf",
            image=None,
            config=MistralOcrConfig(max_retries=1),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )
        assert len(document.regions) == 1
        assert len(recorder.requests) == 2
    else:
        with pytest.raises(MistralOcrProviderError, match=f"HTTP {status}") as raised:
            _ = await provider.process(
                document_url="https://files.example/report.pdf",
                image=None,
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
    provider = MistralOcrSdkProvider(uow=InMemoryUnitOfWork(), storage=FakeStorage())
    with pytest.raises(asyncio.CancelledError):
        _ = await provider.process(
            document_url="https://files.example/report.pdf",
            image=None,
            config=MistralOcrConfig(max_retries=1),
            api_key=SecretStr("key"),
            workspace_id=WORKSPACE_ID,
        )


async def test_isolated_guest_persists_all_four_dependency_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = cast(dict[str, object], ocr_response().json())
    pages = cast(list[dict[str, object]], body["pages"])
    images = cast(list[dict[str, object]], pages[0]["images"])
    images[0]["image_base64"] = "data:image/png;base64,iVBORw=="
    recorder = RequestRecorder(httpx.Response(200, json=body))
    recorder.install(monkeypatch)
    catalog = PluginCatalogManifest.from_plugin(MISTRAL)
    contract = catalog.nodes[0]
    payload = b'{"value":"https://files.example/report.pdf"}'
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/source.json").write_bytes(payload)
    (tmp_path / "outputs").mkdir()
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets/api_key").write_text("provider-secret")
    manifest = tmp_path / "plugin-loader.json"
    manifest.write_bytes(
        PluginGuestLoaderManifest(
            slug=MISTRAL.slug, loader_target="grafy_plugin_mistral.plugin:MISTRAL"
        ).canonical_json_bytes()
    )
    request = PluginInvocationEnvelope(
        invocation_id=uuid4(),
        execution_scope_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        node_id="ocr",
        release=PluginInvocationRelease(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
            slug=MISTRAL.slug,
            revision=1,
            source_digest="a" * 64,
            contract_digest=plugin_contract_digest(catalog),
            protocol_digest=plugin_protocol_digest(),
            descriptor_digest="b" * 64,
        ),
        operator_id=contract.operator_id,
        operator_version=1,
        required_capabilities=contract.required_capabilities,
        config={},
        inputs=(
            PluginInputBinding(
                port="document_url",
                artifact_type=PluginArtifactTypeKey(
                    id=TEXT_VALUE.key.id, schema_version=1
                ),
                groups=(
                    PluginInputArtifactGroup(
                        shape="one",
                        artifacts=(
                            PluginInputArtifactBundle(
                                artifact_id=uuid4(),
                                relative_path="inputs/source.json",
                                byte_count=len(payload),
                                content_sha256=sha256(payload).hexdigest(),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        outputs=tuple(
            PluginOutputDeclaration(
                port=port.name,
                artifact_type=spec.key,
                bundle=spec.bundle,
                shape=port.shape.value,
            )
            for port in contract.outputs
            for spec in catalog.artifact_type_dependencies
            if spec.key == port.artifact_type
        ),
        secrets=(
            PluginSecretBinding(
                name="api_key",
                dependency_digest=node_secret_dependency_sha256({}),
                relative_path="secrets/api_key",
            ),
        ),
        limits=PluginInvocationLimits(),
    )
    (tmp_path / "invocation.json").write_bytes(request.canonical_json_bytes())
    await execute_plugin_invocation(tmp_path, system_loader_manifest_path=manifest)
    result = PluginInvocationResultEnvelope.from_json_bytes(
        (tmp_path / "result.json").read_bytes()
    )
    assert result.status == "succeeded", result.failure
    outputs = {binding.port: binding for binding in result.outputs}
    assert set(outputs) == {"markdown", "blocks", "regions", "figures"}
    assert json.loads(
        (tmp_path / outputs["markdown"].artifacts[0].relative_path).read_bytes()
    ) == {"markdown": "# Invoice\n\nTotal 10"}
    table = load_table_bundle(
        tmp_path / outputs["blocks"].artifacts[0].relative_path,
        max_bytes=1_000_000,
        max_files=10,
        max_rows=10,
        max_columns=20,
        max_chunks=10,
    )
    assert table.rows[1]["text"] == "img-0.png"
    regions = json.loads(
        (tmp_path / outputs["regions"].artifacts[0].relative_path).read_bytes()
    )
    assert regions["width"] == 80
    assert regions["page_index"] == 0
    figure = outputs["figures"].artifacts[0]
    assert (tmp_path / figure.relative_path).read_bytes() == b"\x89PNG"
    assert figure.content_type == "image/png"
    assert figure.metadata["original_filename"] == "img-0.png"
