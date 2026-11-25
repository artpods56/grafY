import base64
import json
from collections.abc import Callable, Mapping
from io import BytesIO
from typing import cast
from uuid import UUID

import httpx
import pytest
from grafy_api.catalog_packs import PACKS, CatalogPolicy
from grafy_api.node_secrets import NodeSecretService
from grafy_api.services.families import build_application_registry
from grafy_core.artifact_contracts import MarkdownValue
from grafy_core.contracts.ocr import DocumentOcrResult
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    NodeExecutionContext,
    ServiceContractKey,
    bind_active_node,
    bind_node_secret_config,
    bind_node_secrets,
)
from grafy_core.plugins import NodeHttpEgressInput
from grafy_core.ports.node_secrets import JsonValue, NodeSecretUnitOfWorkPort
from grafy_plugin_llm.declaration import LLM
from grafy_plugin_llm.ocr import (
    OCR_API_KEY,
    VisionLlmOcrConfig,
    VisionLlmOcrProviderError,
    VisionLlmOcrProviderInput,
    VisionLlmOcrProviderNode,
    VisionLlmOcrReader,
)
from grafy_plugin_llm.ocr_sdk import VisionLlmOcrSdkProvider
from grafy_plugin_llm.openai_compatible import verify_openai_compatible_api_key
from grafy_plugin_llm.plugin import LLM as LOADED_LLM
from grafy_shared.config.catalog import CatalogOverrides
from grafy_shared.config.providers import ProviderSecretsConfig
from grafy_workbench.ocr.nodes import OcrConfig, OcrInput, OcrNode
from PIL import Image
from pydantic import SecretStr, ValidationError

from tests.support.egress import (
    loopback_http_listener,
    no_grants,
    trusted_loopback_destination,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000931")
API_KEY = "secret-provider-key"


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def _encoded_image(image_format: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (12, 34, 56)).save(buffer, format=image_format)
    return buffer.getvalue()


def _image(content: bytes, content_type: str, filename: str = "page.png") -> RasterImage:
    return RasterImage.from_content(
        content, content_type=content_type, filename=filename
    )


class RequestRecorder:
    def __init__(
        self,
        response: httpx.Response | Callable[[httpx.Request], httpx.Response],
    ) -> None:
        self._response = response
        self.requests: list[httpx.Request] = []
        self.client_follow_redirects: list[bool] = []

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
            return recorder.respond(client, request)

        monkeypatch.setattr(httpx.AsyncClient, "send", send)

    def respond(
        self, client: httpx.AsyncClient, request: httpx.Request
    ) -> httpx.Response:
        self.requests.append(request)
        self.client_follow_redirects.append(client.follow_redirects)
        if callable(self._response):
            response = self._response(request)
        else:
            response = self._response
        response.request = request
        return response


class Reporter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context, current, total
        self.messages.append(message)


class FakeNodeSecrets:
    def __init__(self, value: SecretStr) -> None:
        self._value = value
        self.name: str | None = None
        self.dependencies: Mapping[str, JsonValue] | None = None
        self.workspace_id: UUID | None = None

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
        del project_id, graph_id, node_id, actor_user_id
        self.workspace_id = workspace_id
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
    def __init__(self, markdown: str) -> None:
        self._markdown = markdown
        self.api_key: SecretStr | None = None

    async def process(
        self,
        *,
        document: RasterImage | PdfFile,
        config: VisionLlmOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> DocumentOcrResult:
        del document, config
        assert workspace_id == WORKSPACE_ID
        self.api_key = api_key
        return DocumentOcrResult(
            markdown=MarkdownValue(markdown=self._markdown),
            blocks=None,
            regions=None,
        )


def completion_response(
    *,
    content: str | None = "# Page\n\nHello",
    refusal: str | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-ocr",
            "object": "chat.completion",
            "created": 1_700_000_000,
            "model": "provider-model-2026-01",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": content,
                        "refusal": refusal,
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        },
    )


def _provider(
    monkeypatch: pytest.MonkeyPatch,
    recorder: RequestRecorder,
    *,
    egress_policy: object | None = None,
) -> VisionLlmOcrSdkProvider:
    recorder.install(monkeypatch)
    return VisionLlmOcrSdkProvider(
        egress_policy=egress_policy,  # pyright: ignore[reportArgumentType]
    )


def _as_object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _as_object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def _payload(request: httpx.Request) -> dict[str, object]:
    return _as_object_dict(json.loads(request.content))


def _user_parts(payload: Mapping[str, object]) -> list[object]:
    messages = _as_object_list(payload["messages"])
    user = _as_object_dict(messages[-1])
    return _as_object_list(user["content"])


def _image_data_url(parts: list[object]) -> str:
    for part in parts:
        if not isinstance(part, dict):
            continue
        typed = cast(dict[str, object], part)
        if typed.get("type") != "image_url":
            continue
        url = _as_object_dict(typed["image_url"])["url"]
        assert isinstance(url, str)
        return url
    raise AssertionError("image part missing")


def test_config_defaults_and_prompt_fields_use_textareas() -> None:
    config = VisionLlmOcrConfig()
    assert config.base_url == "https://api.openai.com/v1"
    assert config.model == "gpt-4.1-mini"
    assert config.user_prompt == "Transcribe this document page into clean Markdown."
    assert "clean Markdown" in config.system_prompt
    assert "headings" in config.system_prompt
    assert config.temperature == 0.0
    assert config.max_completion_tokens == 4_096
    assert config.timeout_ms == 120_000
    assert config.max_retries == 0

    properties = VisionLlmOcrConfig.model_json_schema()["properties"]
    assert properties["system_prompt"]["title"] == "System instructions"
    assert properties["system_prompt"]["x-grafy-widget"] == "textarea"
    assert properties["user_prompt"]["title"] == "User instructions"
    assert properties["user_prompt"]["x-grafy-widget"] == "textarea"
    assert properties["model"]["title"] == "Model"
    assert properties["base_url"]["x-grafy-advanced"] is True
    assert properties["temperature"] == {
        **properties["temperature"],
        "x-grafy-advanced": True,
        "x-grafy-widget": "slider",
    }
    assert properties["max_completion_tokens"]["x-grafy-advanced"] is True
    assert properties["timeout_ms"]["x-grafy-advanced"] is True
    assert properties["max_retries"]["x-grafy-advanced"] is True


def test_config_accepts_https_and_loopback_http() -> None:
    assert (
        VisionLlmOcrConfig(base_url="https://Example.COM/v1/").base_url
        == "https://example.com/v1"
    )
    assert (
        VisionLlmOcrConfig(base_url="http://localhost:4000/v1/").base_url
        == "http://localhost:4000/v1"
    )
    assert (
        VisionLlmOcrConfig(base_url="http://127.0.0.1:4000/v1").base_url
        == "http://127.0.0.1:4000/v1"
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.com/v1",
        "https://user:password@example.com/v1",
        "https://api.example.com/v1?tenant=one",
        "https://api.example.com/v1#fragment",
        " https://api.example.com/v1",
    ],
)
def test_config_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError):
        VisionLlmOcrConfig(base_url=base_url)


def test_provider_node_is_markdown_only_and_reuses_the_openai_verifier() -> None:
    assert LOADED_LLM is LLM
    assert VisionLlmOcrReader.features == frozenset()
    assert VisionLlmOcrProviderNode.operator_id == "llm.ocr.provider"
    assert VisionLlmOcrProviderNode.input_contract.ports == {}
    engine = VisionLlmOcrProviderNode.output_contract.ports["engine"]
    assert engine.kind == "service"
    assert engine.service_contracts == (ServiceContractKey("ocr.document", 1),)
    assert engine.service_features[0].features == ()
    registration = next(
        item for item in LLM.nodes if item.key == ("llm.ocr.provider", 1)
    )
    assert registration.secret_inputs == (OCR_API_KEY,)
    assert registration.secret_inputs[0].verifier is verify_openai_compatible_api_key
    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    )
    assert registration.http_egress is not None
    assert registration.http_egress.configured_inputs == (
        NodeHttpEgressInput(config_field="base_url"),
    )
    chat = next(
        item
        for item in LLM.nodes
        if item.key == ("llm.openai_compatible.chat_completion", 1)
    )
    assert registration.secret_inputs[0].verifier is chat.secret_inputs[0].verifier


async def test_ocr_node_returns_markdown_without_blocks_or_regions() -> None:
    secret = SecretStr(API_KEY)
    secrets = FakeNodeSecrets(secret)
    provider = FakeProvider("# Invoice")
    node = VisionLlmOcrProviderNode(provider=provider, node_secrets=secrets)
    config = VisionLlmOcrConfig(base_url="https://gateway.example/v1/")
    supplied = await node.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="vision-ocr"),
        config,
        VisionLlmOcrProviderInput(),
    )

    assert secrets.name == "api_key"
    assert secrets.dependencies == {"base_url": "https://gateway.example/v1"}
    assert supplied.engine.features == frozenset()
    output = await OcrNode().run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="read"),
        OcrConfig(),
        OcrInput(document=_image(b"png-bytes", "image/png"), engine=supplied.engine),
    )
    assert provider.api_key is secret
    assert output.markdown.markdown == "# Invoice"
    assert output.blocks is None
    assert output.regions is None


async def test_bound_secret_is_read_with_require() -> None:
    secret = SecretStr(API_KEY)
    secrets = FakeNodeSecrets(secret)
    registration = next(
        item for item in LLM.nodes if item.key == ("llm.ocr.provider", 1)
    )
    config = VisionLlmOcrConfig()
    context = bind_node_secret_config(
        bind_node_secrets(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="vision-ocr"),
            secrets,
            registration.secret_inputs,
        ),
        config,
    )
    assert context.secrets.workspace_id == WORKSPACE_ID
    node = VisionLlmOcrProviderNode(
        provider=FakeProvider("ok"), node_secrets=secrets
    )
    await node.run(context, config, VisionLlmOcrProviderInput())
    assert secrets.dependencies == {"base_url": config.base_url}


async def test_sdk_posts_prompts_and_image_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(completion_response(content="# Transcribed"))
    provider = _provider(monkeypatch, recorder)
    reporter = Reporter()
    context = NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        node_id="read",
        progress_reporter=reporter,
    )
    raw = _png_bytes()
    document = _image(raw, "image/png", "scan.png")
    config = VisionLlmOcrConfig(
        base_url="https://gateway.example/v1/",
        model="vision-model",
        temperature=0.0,
        max_completion_tokens=512,
        system_prompt="Keep the reading order.",
        user_prompt="Transcribe this page.",
    )

    async with bind_active_node(context):
        result = await provider.process(
            document=document,
            config=config,
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )

    assert result.markdown.markdown == "# Transcribed"
    assert result.blocks is None
    assert result.regions is None
    assert reporter.messages == ["Preparing image…", "Calling Vision LLM OCR…"]
    assert recorder.client_follow_redirects == [False]
    request = recorder.requests[0]
    assert str(request.url) == "https://gateway.example/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    payload = _payload(request)
    assert payload["model"] == "vision-model"
    assert payload["temperature"] == 0.0
    assert payload["max_completion_tokens"] == 512
    messages = _as_object_list(payload["messages"])
    assert _as_object_dict(messages[0]) == {
        "role": "system",
        "content": "Keep the reading order.",
    }
    parts = _user_parts(payload)
    assert parts[0] == {"type": "text", "text": "Transcribe this page."}
    url = _image_data_url(parts)
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == raw


async def test_blank_prompts_omit_text_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    await provider.process(
        document=_image(b"png", "image/png"),
        config=VisionLlmOcrConfig(system_prompt="  \n", user_prompt=""),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
    )
    payload = _payload(recorder.requests[0])
    messages = _as_object_list(payload["messages"])
    assert len(messages) == 1
    parts = _user_parts(payload)
    assert len(parts) == 1
    assert _as_object_dict(parts[0])["type"] == "image_url"


@pytest.mark.parametrize(
    ("content_type", "data_mime"),
    [
        ("image/jpeg", "image/jpeg"),
        ("image/jpg", "image/jpeg"),
        ("image/webp", "image/webp"),
        ("image/gif", "image/gif"),
    ],
)
async def test_direct_image_types_keep_their_bytes(
    monkeypatch: pytest.MonkeyPatch, content_type: str, data_mime: str
) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    raw = b"image-bytes"
    await provider.process(
        document=_image(raw, content_type, "scan.bin"),
        config=VisionLlmOcrConfig(system_prompt="", user_prompt=""),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
    )
    url = _image_data_url(_user_parts(_payload(recorder.requests[0])))
    assert url.startswith(f"data:{data_mime};base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == raw


@pytest.mark.parametrize(
    ("image_format", "content_type"),
    [("TIFF", "image/tiff"), ("BMP", "image/bmp")],
)
async def test_tiff_and_bmp_are_converted_to_png(
    monkeypatch: pytest.MonkeyPatch, image_format: str, content_type: str
) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    original = _encoded_image(image_format)
    await provider.process(
        document=_image(original, content_type, f"scan.{image_format.lower()}"),
        config=VisionLlmOcrConfig(),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
    )
    url = _image_data_url(_user_parts(_payload(recorder.requests[0])))
    assert url.startswith("data:image/png;base64,")
    converted = base64.b64decode(url.split(",", 1)[1])
    assert converted.startswith(b"\x89PNG")
    assert converted != original
    with Image.open(BytesIO(converted)) as image:
        assert image.format == "PNG"
        assert image.size == (2, 2)


async def test_pdf_is_rejected_before_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    document = PdfFile.from_content(
        b"%PDF-1.4", content_type="application/pdf", filename="doc.pdf"
    )
    with pytest.raises(
        VisionLlmOcrProviderError,
        match="raster images only; PDF documents are not supported yet",
    ):
        await provider.process(
            document=document,
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert recorder.requests == []


async def test_unknown_content_type_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    with pytest.raises(
        VisionLlmOcrProviderError, match="unsupported content type 'image/svg\\+xml'"
    ):
        await provider.process(
            document=_image(b"<svg/>", "image/svg+xml", "scan.svg"),
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert recorder.requests == []


async def test_oversized_image_names_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    image = RasterImage(
        content_type="image/png",
        byte_size=20_000_001,
        filename="huge.png",
        content=b"x",
        storage=None,
        bucket=None,
        object_key=None,
    )
    with pytest.raises(VisionLlmOcrProviderError, match="huge.png exceeds the 20000000-byte limit"):
        await provider.process(
            document=image,
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert recorder.requests == []


async def test_read_failure_hides_the_storage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(completion_response())
    provider = _provider(monkeypatch, recorder)
    image = _image(b"png", "image/png", "page.png")

    async def fail_read(*, max_bytes: int) -> bytes:
        del max_bytes
        raise OSError(f"disk included {API_KEY}")

    monkeypatch.setattr(image, "read", fail_read)
    with pytest.raises(VisionLlmOcrProviderError, match="Failed to read page.png") as captured:
        await provider.process(
            document=image,
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(captured.value)


@pytest.mark.parametrize(
    ("status_code", "guidance"),
    [
        (401, "configured API key"),
        (429, "rate limit or account quota"),
        (500, "currently unavailable"),
    ],
)
async def test_status_errors_hide_the_provider_body(
    monkeypatch: pytest.MonkeyPatch, status_code: int, guidance: str
) -> None:
    echoed = f"provider echoed {API_KEY} in an error"
    recorder = RequestRecorder(httpx.Response(status_code, text=echoed))
    provider = _provider(monkeypatch, recorder)
    with pytest.raises(VisionLlmOcrProviderError, match=guidance) as captured:
        await provider.process(
            document=_image(b"png", "image/png"),
            config=VisionLlmOcrConfig(model="vision-model"),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    message = str(captured.value)
    assert f"HTTP {status_code}" in message
    assert "vision-model" in message
    assert API_KEY not in message
    assert echoed not in message
    assert captured.value.__cause__ is None


async def test_refusal_hides_the_refusal_text(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = "private refusal details"
    recorder = RequestRecorder(completion_response(content="", refusal=refusal))
    provider = _provider(monkeypatch, recorder)
    with pytest.raises(VisionLlmOcrProviderError, match="was refused") as captured:
        await provider.process(
            document=_image(b"png", "image/png"),
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert refusal not in str(captured.value)
    assert API_KEY not in str(captured.value)


async def test_empty_content_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RequestRecorder(completion_response(content=""))
    provider = _provider(monkeypatch, recorder)
    with pytest.raises(VisionLlmOcrProviderError, match="did not contain text"):
        await provider.process(
            document=_image(b"png", "image/png"),
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )


async def test_invalid_completion_does_not_echo_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(httpx.Response(200, json={"unexpected": API_KEY}))
    provider = _provider(monkeypatch, recorder)
    with pytest.raises(VisionLlmOcrProviderError, match="did not match the SDK response model") as captured:
        await provider.process(
            document=_image(b"png", "image/png"),
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(captured.value)
    assert captured.value.__cause__ is None


def timeout_response(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout(f"transport included {API_KEY}", request=request)


def connection_error_response(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"transport included {API_KEY}", request=request)


async def test_timeout_and_connection_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout_provider = _provider(monkeypatch, RequestRecorder(timeout_response))
    with pytest.raises(VisionLlmOcrProviderError, match="timed out") as timed_out:
        await timeout_provider.process(
            document=_image(b"png", "image/png"),
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(timed_out.value)

    connection_provider = _provider(
        monkeypatch, RequestRecorder(connection_error_response)
    )
    with pytest.raises(VisionLlmOcrProviderError, match="could not connect") as failed:
        await connection_provider.process(
            document=_image(b"png", "image/png"),
            config=VisionLlmOcrConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(failed.value)
    assert failed.value.__cause__ is None


async def test_local_server_is_dialed_only_when_egress_allows_it() -> None:
    body = completion_response(content="# Local").content
    async with loopback_http_listener(body=body) as listener:
        config = VisionLlmOcrConfig(base_url=f"{listener.base_url}/v1")
        document = _image(_png_bytes(), "image/png")

        async def read(policy: object) -> str:
            provider = VisionLlmOcrSdkProvider(
                egress_policy=policy,  # pyright: ignore[reportArgumentType]
            )
            result = await provider.process(
                document=document,
                config=config,
                api_key=SecretStr(API_KEY),
                workspace_id=WORKSPACE_ID,
            )
            return result.markdown.markdown

        assert await read(trusted_loopback_destination()) == "# Local"
        request = listener.requests[0]
        assert request.path == "/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        payload = _as_object_dict(json.loads(request.body))
        messages = _as_object_list(payload["messages"])
        assert _as_object_dict(messages[0])["role"] == "system"
        assert "image_url" in request.body.decode("utf-8")

        with pytest.raises(VisionLlmOcrProviderError, match="may not be dialed") as raised:
            await read(no_grants())
        assert "127.0.0.1" in str(raised.value)
        assert API_KEY not in str(raised.value)
        assert len(listener.requests) == 1


def _deployment_service(
    key: str | None, endpoint: str = "https://api.openai.com/v1"
) -> NodeSecretService:
    def unused_uow() -> NodeSecretUnitOfWorkPort:
        raise AssertionError("deployment default does not open a unit of work")

    return NodeSecretService(
        unit_of_work_factory=unused_uow,
        plugin_registry=build_application_registry(),
        encryption_key=None,
        provider_secrets=ProviderSecretsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            openai_api_key=None if key is None else SecretStr(key),
            openai_base_url=endpoint,  # pyright: ignore[reportCallIssue]
        ),
    )


def _deployment_default(
    service: NodeSecretService,
    operator_id: str,
    dependencies: Mapping[str, JsonValue],
    name: str = "api_key",
) -> SecretStr | None:
    return service._deployment_default(  # pyright: ignore[reportPrivateUsage]
        operator_id, name, dependencies
    )


def test_deployment_default_treats_vision_ocr_like_chat_completion() -> None:
    endpoint = "https://llm.example/v1"
    service = _deployment_service("default-key", endpoint)
    dependencies = {"base_url": "https://llm.example/v1/"}
    ocr_key = _deployment_default(service, "llm.ocr.provider", dependencies)
    chat_key = _deployment_default(
        service, "llm.openai_compatible.chat_completion", dependencies
    )
    assert ocr_key is not None
    assert chat_key is not None
    assert ocr_key.get_secret_value() == "default-key"
    assert chat_key.get_secret_value() == ocr_key.get_secret_value()
    assert (
        _deployment_default(
            service,
            "llm.ocr.provider",
            {"base_url": "https://other.example/v1"},
        )
        is None
    )
    assert (
        _deployment_default(service, "llm.ocr.provider", {"base_url": "not a url"})
        is None
    )
    assert _deployment_default(service, "llm.ocr.provider", dependencies, name="other") is None
    assert _deployment_default(service, "mistral.ocr.provider", dependencies) is None
    assert (
        _deployment_default(_deployment_service("   ", endpoint), "llm.ocr.provider", dependencies)
        is None
    )
    assert (
        _deployment_default(_deployment_service(None, endpoint), "llm.ocr.provider", dependencies)
        is None
    )


def test_document_ocr_pack_includes_the_vision_provider() -> None:
    pack = next(item for item in PACKS if item.slug == "document_ocr")
    assert ServiceContractKey("ocr.document", 1) in pack.include_providers_for
    registry = build_application_registry()
    registration = registry.node_registration("llm.ocr.provider", 1)
    policy = CatalogPolicy(registry, CatalogOverrides())
    assert policy.pack_slugs_for(registration) == ("document_ocr",)
    described = next(
        item for item in policy.packs if item.definition.slug == "document_ocr"
    )
    assert described.provider_count == 3
    assert described.operator_count == 2
