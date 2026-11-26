import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from grafy_api.catalog_packs import PACKS, CatalogPolicy
from grafy_api.node_secrets import NodeSecretService
from grafy_api.services.families import build_application_registry
from grafy_core.artifacts import NoConfig
from grafy_core.contracts.ocr import TextReading, TextRegion, TiffPage
from grafy_core.documents import TiffFile
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.node_ports import Ref
from grafy_core.nodes import (
    NodeExecutionContext,
    ServiceContractKey,
    bind_active_node,
    bind_node_secret_config,
    bind_node_secrets,
)
from grafy_core.plugins import NodeHttpEgressInput
from grafy_core.ports.node_secrets import JsonValue, NodeSecretUnitOfWorkPort
from grafy_core.provider_cache import InMemoryCacheStore, ProviderCache
from grafy_plugin_llm.crop_reader import (
    VisionLlmCropReaderConfig,
    VisionLlmCropReaderError,
    VisionLlmCropReaderInput,
    VisionLlmCropReaderNode,
    VisionLlmCropTextReader,
)
from grafy_plugin_llm.crop_reader_sdk import VisionLlmCropReaderSdkProvider
from grafy_plugin_llm.crop_sheet import (
    MAX_CROP_BYTES,
    CropSheetError,
    pack_crop_sheets,
)
from grafy_plugin_llm.declaration import LLM
from grafy_plugin_llm.ocr import OCR_API_KEY
from grafy_plugin_llm.openai_compatible import verify_openai_compatible_api_key
from grafy_plugin_llm.plugin import LLM as LOADED_LLM
from grafy_plugin_map_toponyms.text_regions import TiffPixelWindow, TiffTextRegions
from grafy_plugin_map_toponyms.tiff_recognition import (
    ReadTiffTextNode,
    RecognizeInput,
)
from grafy_shared.config.catalog import CatalogOverrides
from grafy_shared.config.providers import ProviderSecretsConfig
from PIL import Image, ImageDraw
from pydantic import SecretStr, ValidationError

from tests.support.egress import (
    loopback_http_listener,
    no_grants,
    trusted_loopback_destination,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000932")
API_KEY = "secret-crop-reader-key"


def _crop_png(
    width: int = 80,
    height: int = 24,
    *,
    color: tuple[int, int, int] = (20, 40, 60),
    mode: str = "RGB",
) -> bytes:
    buffer = BytesIO()
    if mode == "RGBA":
        image = Image.new("RGBA", (width, height), (*color, 180))
    else:
        image = Image.new("RGB", (width, height), color)
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
        self.updates: list[tuple[str, int | None, int | None]] = []

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        del context
        self.updates.append((message, current, total))


class FakeNodeSecrets:
    def __init__(self, value: SecretStr) -> None:
        self._value = value
        self.name: str | None = None
        self.dependencies: Mapping[str, JsonValue] | None = None

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
        del workspace_id, project_id, graph_id, node_id, actor_user_id
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


class FakeCropProvider:
    def __init__(self, readings: list[str]) -> None:
        self._readings = readings
        self.api_key: SecretStr | None = None
        self.calls: list[int] = []

    async def recognize(
        self,
        *,
        crops: Sequence[bytes],
        config: VisionLlmCropReaderConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> list[TextReading]:
        assert workspace_id == WORKSPACE_ID
        self.api_key = api_key
        self.calls.append(len(crops))
        return [
            TextReading(
                text=self._readings[index % len(self._readings)],
                confidence=None,
                model=config.model,
            )
            for index in range(len(crops))
        ]


def completion_response(
    *,
    content: str | None,
    model: str = "vision-crop-2026-01",
    refusal: str | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-crop",
            "object": "chat.completion",
            "created": 1_700_000_000,
            "model": model,
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
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        },
    )


def _as_object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _as_object_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast(list[object], value)


def _payload(request: httpx.Request) -> dict[str, object]:
    return _as_object_dict(json.loads(request.content))


def _user_text(payload: Mapping[str, object]) -> str:
    messages = _as_object_list(payload["messages"])
    user = _as_object_dict(messages[-1])
    parts = _as_object_list(user["content"])
    text_part = _as_object_dict(parts[0])
    text = text_part["text"]
    assert isinstance(text, str)
    return text


def _image_data_url(payload: Mapping[str, object]) -> str:
    messages = _as_object_list(payload["messages"])
    user = _as_object_dict(messages[-1])
    parts = _as_object_list(user["content"])
    image_part = _as_object_dict(parts[1])
    url = _as_object_dict(image_part["image_url"])["url"]
    assert isinstance(url, str)
    return url


def test_config_defaults_and_ui_metadata() -> None:
    config = VisionLlmCropReaderConfig()
    assert config.base_url == "https://api.openai.com/v1"
    assert config.model == "gpt-4.1-mini"
    assert config.temperature == 0.0
    assert config.max_completion_tokens == 4_096
    assert config.max_sheet_crops == 16
    assert config.max_sheet_edge == 1_536
    assert config.max_concurrency == 4
    assert config.timeout_ms == 120_000
    assert config.max_retries == 0

    properties = VisionLlmCropReaderConfig.model_json_schema()["properties"]
    assert properties["system_prompt"]["x-grafy-widget"] == "textarea"
    assert properties["user_prompt"]["x-grafy-widget"] == "textarea"
    assert properties["base_url"]["x-grafy-advanced"] is True
    assert properties["temperature"]["x-grafy-widget"] == "slider"
    assert properties["temperature"]["x-grafy-advanced"] is True
    assert properties["max_sheet_crops"]["x-grafy-advanced"] is True
    assert properties["max_sheet_edge"]["x-grafy-advanced"] is True
    assert properties["max_concurrency"]["x-grafy-advanced"] is True
    assert properties["timeout_ms"]["x-grafy-advanced"] is True
    assert properties["max_retries"]["x-grafy-advanced"] is True


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.com/v1",
        "https://user:pass@example.com/v1",
        "https://api.example.com/v1?x=1",
        "https://api.example.com/v1#frag",
    ],
)
def test_config_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError):
        VisionLlmCropReaderConfig(base_url=base_url)


def test_node_contract_registration_pack_and_deployment_default() -> None:
    assert LOADED_LLM is LLM
    assert VisionLlmCropReaderNode.operator_id == "llm.crop_reader.provider"
    assert VisionLlmCropReaderNode.input_contract.ports == {}
    output_port = VisionLlmCropReaderNode.output_contract.ports["recognizer"]
    assert output_port.kind == "service"
    assert output_port.service_contracts == (ServiceContractKey("ocr.crop_reader", 1),)

    registration = next(
        item for item in LLM.nodes if item.key == ("llm.crop_reader.provider", 1)
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

    registry = build_application_registry()
    policy = CatalogPolicy(registry, CatalogOverrides(), PACKS)
    app_registration = registry.node_registration("llm.crop_reader.provider", 1)
    assert policy.pack_slugs_for(app_registration) == ("map_toponyms",)

    def unused_uow() -> NodeSecretUnitOfWorkPort:
        raise AssertionError("deployment default does not open a unit of work")

    endpoint = "https://llm.example/v1"
    secret_service = NodeSecretService(
        unit_of_work_factory=unused_uow,
        plugin_registry=registry,
        encryption_key=None,
        provider_secrets=ProviderSecretsConfig(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            openai_api_key=SecretStr("default-crop-key"),
            openai_base_url=endpoint,  # pyright: ignore[reportCallIssue]
        ),
    )
    resolved = secret_service._deployment_default(  # pyright: ignore[reportPrivateUsage]
        "llm.crop_reader.provider",
        "api_key",
        {"base_url": "https://llm.example/v1/"},
    )
    assert resolved is not None
    assert resolved.get_secret_value() == "default-crop-key"


def test_pack_crop_sheets_packs_rows_splits_by_budget_and_handles_edge_sizes() -> None:
    assert pack_crop_sheets([], max_crops=16, max_edge=1_536) == []

    # 10 crops with max_crops=4 -> 3 sheets (4, 4, 2) covering indices 0..9 in order.
    crops = [_crop_png(120, 48, color=(i * 20, 30, 50)) for i in range(10)]
    sheets = pack_crop_sheets(crops, max_crops=4, max_edge=1_024)
    assert [sheet.indices for sheet in sheets] == [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (8, 9),
    ]
    for sheet in sheets:
        assert sheet.width <= 1_024
        assert sheet.height <= 1_024
        with Image.open(BytesIO(sheet.png_bytes)) as rendered:
            assert rendered.format == "PNG"
            assert rendered.size == (sheet.width, sheet.height)

    # Pixel-budget split when crops are tall/wide relative to max_edge.
    large_crops = [_crop_png(380, 380) for _ in range(3)]
    budget_sheets = pack_crop_sheets(large_crops, max_crops=16, max_edge=512)
    assert [sheet.indices for sheet in budget_sheets] == [(0,), (1,), (2,)]

    # Oversized crop and RGBA tiny crop both pack cleanly without raising.
    mixed = [_crop_png(2_800, 500), _crop_png(30, 12, mode="RGBA")]
    mixed_sheets = pack_crop_sheets(mixed, max_crops=16, max_edge=512)
    assert sum(len(sheet.indices) for sheet in mixed_sheets) == 2
    for sheet in mixed_sheets:
        assert sheet.width <= 512
        assert sheet.height <= 512

    with pytest.raises(CropSheetError, match="Could not decode text crop 1"):
        pack_crop_sheets([b"not-an-image"], max_crops=4, max_edge=512)

    with pytest.raises(CropSheetError, match="exceeds the"):
        pack_crop_sheets([b"x" * (MAX_CROP_BYTES + 1)], max_crops=4, max_edge=512)


def test_cache_identity_includes_output_affecting_options_only() -> None:
    provider = FakeCropProvider(["ok"])
    base = VisionLlmCropTextReader(
        config=VisionLlmCropReaderConfig(
            model="gpt-4.1-mini",
            system_prompt="Read Cyrillic.",
            timeout_ms=60_000,
            max_retries=0,
            max_concurrency=2,
        ),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
        provider=provider,
    )
    same_answers = VisionLlmCropTextReader(
        config=VisionLlmCropReaderConfig(
            model="gpt-4.1-mini",
            system_prompt="Read Cyrillic.",
            timeout_ms=180_000,
            max_retries=3,
            max_concurrency=8,
        ),
        api_key=SecretStr("different-secret"),
        workspace_id=WORKSPACE_ID,
        provider=provider,
    )
    changed_prompt = VisionLlmCropTextReader(
        config=VisionLlmCropReaderConfig(
            model="gpt-4.1-mini",
            system_prompt="Read Latin.",
        ),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
        provider=provider,
    )

    assert base.cache_identity() == same_answers.cache_identity()
    assert base.cache_identity().revision is not None
    assert API_KEY not in json.dumps(base.cache_identity().options_payload())
    assert base.cache_identity() != changed_prompt.cache_identity()

    # Very long model names still produce a valid <= 255 char revision.
    long_model = VisionLlmCropTextReader(
        config=VisionLlmCropReaderConfig(model="m" * 300),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
        provider=provider,
    )
    long_rev = long_model.cache_identity().revision
    assert long_rev is not None
    assert len(long_rev) <= 255


async def test_node_resolves_secret_and_supports_bound_context() -> None:
    secret = SecretStr(API_KEY)
    secrets = FakeNodeSecrets(secret)
    provider = FakeCropProvider(["Минск"])
    config = VisionLlmCropReaderConfig(
        base_url="https://gateway.example/v1/",
        max_sheet_crops=12,
        max_concurrency=3,
    )

    node = VisionLlmCropReaderNode(provider=provider, node_secrets=secrets)
    output = await node.run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="vlm-crop"),
        config,
        VisionLlmCropReaderInput(),
    )
    assert secrets.name == "api_key"
    assert secrets.dependencies == {"base_url": "https://gateway.example/v1"}
    assert output.recognizer.preferred_batch_size == 36

    readings = await output.recognizer.recognize([_crop_png()])
    assert provider.api_key is secret
    assert readings == [TextReading(text="Минск", confidence=None, model=config.model)]

    registration = next(
        item for item in LLM.nodes if item.key == ("llm.crop_reader.provider", 1)
    )
    bound_context = bind_node_secret_config(
        bind_node_secrets(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="vlm-crop"),
            secrets,
            registration.secret_inputs,
        ),
        config,
    )
    await node.run(bound_context, config, VisionLlmCropReaderInput())


async def test_sdk_reads_contact_sheets_reports_progress_and_accepts_fenced_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = _payload(request)
        text = _user_text(payload)
        assert "response_format" in payload
        if "IDs 1 through 3" in text:
            body = '```json\n{"readings": [{"id": 1, "text": "One"}, {"id": 2, "text": ""}, {"id": 3, "text": "Three"}]}\n```'
        else:
            body = json.dumps({"readings": [{"id": 1, "text": "Four"}]})
        return completion_response(content=body, model="vlm-exact-1")

    recorder = RequestRecorder(respond)
    recorder.install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()
    reporter = Reporter()
    context = NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        node_id="read-text",
        progress_reporter=reporter,
    )
    config = VisionLlmCropReaderConfig(
        base_url="https://gateway.example/v1/",
        model="vision-model",
        system_prompt="Historical Cyrillic maps.",
        user_prompt="Transcribe all map labels.",
        max_sheet_crops=3,
        max_concurrency=1,
    )

    async with bind_active_node(context):
        readings = await provider.recognize(
            crops=[_crop_png(90, 30) for _ in range(4)],
            config=config,
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )

    assert [item.text for item in readings] == ["One", "", "Three", "Four"]
    assert all(item.model == "vlm-exact-1" for item in readings)
    assert all(item.confidence is None for item in readings)
    assert len(recorder.requests) == 2
    assert recorder.client_follow_redirects == [False, False]
    assert reporter.updates == [
        ("Calling Vision LLM text recognizer…", 0, 4),
        ("Calling Vision LLM text recognizer…", 3, 4),
        ("Calling Vision LLM text recognizer…", 4, 4),
    ]
    first_payload = _payload(recorder.requests[0])
    system_msg = _as_object_dict(_as_object_list(first_payload["messages"])[0])
    assert "Historical Cyrillic maps." in cast(str, system_msg["content"])
    assert '{"readings":' in cast(str, system_msg["content"])
    assert _image_data_url(first_payload).startswith("data:image/png;base64,")


async def test_sdk_falls_back_when_endpoint_rejects_json_schema_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_response_formats: list[bool] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = _payload(request)
        has_format = "response_format" in payload
        seen_response_formats.append(has_format)
        if has_format:
            return httpx.Response(400, text="json_schema unsupported")
        return completion_response(
            content=json.dumps({"readings": [{"id": 1, "text": "Alpha"}]})
        )

    recorder = RequestRecorder(respond)
    recorder.install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()
    config = VisionLlmCropReaderConfig(max_sheet_crops=1, max_concurrency=1)

    readings = await provider.recognize(
        crops=[_crop_png(), _crop_png()],
        config=config,
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
    )

    assert [item.text for item in readings] == ["Alpha", "Alpha"]
    # First sheet probed json_schema -> 400 -> retried without; second skipped json_schema.
    assert seen_response_formats == [True, False, False]


async def test_sdk_bisects_sheet_on_missing_id_or_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_counts: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        text = _user_text(_payload(request))
        if "IDs 1 through 4" in text:
            expected_counts.append(4)
            # Drops ID 3 -> triggers bisect into 2 + 2.
            return completion_response(
                content=json.dumps(
                    {
                        "readings": [
                            {"id": 1, "text": "A"},
                            {"id": 2, "text": "B"},
                            {"id": 4, "text": "D"},
                        ]
                    }
                )
            )
        if "IDs 1 through 2" in text:
            expected_counts.append(2)
            # First half succeeds, second half returns broken JSON -> bisects into 1 + 1.
            if expected_counts.count(2) == 1:
                return completion_response(
                    content=json.dumps(
                        {
                            "readings": [
                                {"id": 1, "text": "A"},
                                {"id": 2, "text": "B"},
                            ]
                        }
                    )
                )
            return completion_response(content="not valid json")
        expected_counts.append(1)
        idx = expected_counts.count(1)
        return completion_response(
            content=json.dumps({"readings": [{"id": 1, "text": f"Leaf-{idx}"}]})
        )

    recorder = RequestRecorder(respond)
    recorder.install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()
    config = VisionLlmCropReaderConfig(max_sheet_crops=4, max_concurrency=1)

    readings = await provider.recognize(
        crops=[_crop_png(60, 24) for _ in range(4)],
        config=config,
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
    )

    assert expected_counts == [4, 2, 2, 1, 1]
    assert [item.text for item in readings] == ["A", "B", "Leaf-1", "Leaf-2"]


async def test_sdk_raises_user_facing_error_when_single_crop_still_fails_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(completion_response(content="still not json"))
    recorder.install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()

    with pytest.raises(VisionLlmCropReaderError, match="returned invalid JSON"):
        await provider.recognize(
            crops=[_crop_png()],
            config=VisionLlmCropReaderConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )


async def test_sdk_bounds_sheet_concurrency_with_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_flight = 0
    peak_in_flight = 0
    two_running = asyncio.Event()
    release = asyncio.Event()

    async def send(
        client: httpx.AsyncClient,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: object = None,
        follow_redirects: object = None,
    ) -> httpx.Response:
        del client, stream, auth, follow_redirects
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        if in_flight == 2:
            two_running.set()
        await release.wait()
        in_flight -= 1
        response = completion_response(
            content=json.dumps({"readings": [{"id": 1, "text": "ok"}]})
        )
        response.request = request
        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    provider = VisionLlmCropReaderSdkProvider()
    config = VisionLlmCropReaderConfig(max_sheet_crops=1, max_concurrency=2)

    task = asyncio.create_task(
        provider.recognize(
            crops=[_crop_png() for _ in range(4)],
            config=config,
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    )
    await two_running.wait()
    assert peak_in_flight == 2
    release.set()
    readings = await task
    assert len(readings) == 4
    assert peak_in_flight == 2


@pytest.mark.parametrize(
    ("status_code", "guidance"),
    [
        (401, "configured API key"),
        (429, "rate limit or account quota"),
        (500, "currently unavailable"),
    ],
)
async def test_sdk_status_errors_hide_provider_body_and_api_key(
    monkeypatch: pytest.MonkeyPatch, status_code: int, guidance: str
) -> None:
    echoed = f"provider echoed {API_KEY}"
    recorder = RequestRecorder(httpx.Response(status_code, text=echoed))
    recorder.install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()

    with pytest.raises(VisionLlmCropReaderError, match=guidance) as captured:
        await provider.recognize(
            crops=[_crop_png()],
            config=VisionLlmCropReaderConfig(model="vision-model"),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    message = str(captured.value)
    assert f"HTTP {status_code}" in message
    assert API_KEY not in message
    assert echoed not in message
    assert captured.value.__cause__ is None


async def test_sdk_refusal_timeout_and_connection_errors_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal_recorder = RequestRecorder(
        completion_response(content="", refusal=f"refused {API_KEY}")
    )
    refusal_recorder.install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()
    with pytest.raises(VisionLlmCropReaderError, match="was refused") as refused:
        await provider.recognize(
            crops=[_crop_png()],
            config=VisionLlmCropReaderConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(refused.value)

    def timeout_response(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout {API_KEY}", request=request)

    RequestRecorder(timeout_response).install(monkeypatch)
    with pytest.raises(VisionLlmCropReaderError, match="timed out") as timed_out:
        await provider.recognize(
            crops=[_crop_png()],
            config=VisionLlmCropReaderConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(timed_out.value)

    def conn_error_response(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"conn {API_KEY}", request=request)

    RequestRecorder(conn_error_response).install(monkeypatch)
    with pytest.raises(VisionLlmCropReaderError, match="could not connect") as failed:
        await provider.recognize(
            crops=[_crop_png()],
            config=VisionLlmCropReaderConfig(),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(failed.value)


async def test_local_server_is_dialed_only_when_egress_allows_it() -> None:
    body = completion_response(
        content=json.dumps({"readings": [{"id": 1, "text": "Полоцк"}]})
    ).content
    async with loopback_http_listener(body=body) as listener:
        config = VisionLlmCropReaderConfig(base_url=f"{listener.base_url}/v1")

        async def run(policy: object) -> list[TextReading]:
            provider = VisionLlmCropReaderSdkProvider(
                egress_policy=policy,  # pyright: ignore[reportArgumentType]
            )
            return await provider.recognize(
                crops=[_crop_png()],
                config=config,
                api_key=SecretStr(API_KEY),
                workspace_id=WORKSPACE_ID,
            )

        readings = await run(trusted_loopback_destination())
        assert [item.text for item in readings] == ["Полоцк"]
        assert len(listener.requests) == 1
        assert listener.requests[0].path == "/v1/chat/completions"
        assert listener.requests[0].headers["authorization"] == f"Bearer {API_KEY}"
        encoded_body = listener.requests[0].body.decode("utf-8")
        assert "data:image/png;base64," in encoded_body

        with pytest.raises(
            VisionLlmCropReaderError, match="may not be dialed"
        ) as blocked:
            await run(no_grants())
        assert "127.0.0.1" in str(blocked.value)
        assert API_KEY not in str(blocked.value)
        assert len(listener.requests) == 1


async def test_read_tiff_text_node_caches_and_busts_on_prompt_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, artifact_id = uuid4(), uuid4()
    page_side = 500
    scan = Image.new("RGB", (page_side, page_side), "white")
    draw = ImageDraw.Draw(scan)
    regions: list[TextRegion] = []
    for index in range(10):
        left = 10 + (index % 5) * 90
        top = 10 + (index // 5) * 80
        right, bottom = left + 40 + index * 2, top + 20
        draw.rectangle((left, top, right, bottom), fill="black")
        regions.append(
            TextRegion(
                polygon=[(left, top), (right, top), (right, bottom), (left, bottom)]
            )
        )

    async def read(*, col: int, row: int, width: int, height: int) -> bytes:
        buf = BytesIO()
        scan.crop((col, row, col + width, row + height)).save(buf, format="PNG")
        return buf.getvalue()

    async def open_page(
        workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        del workspace_id, artifact_id
        return TiffPage(page_side, page_side, read, source_sha256="bb" * 32, page=page)

    call_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        payload = _payload(request)
        text = _user_text(payload)
        # Parse how many crops were packed onto this sheet from the count instruction.
        if "IDs 1 through " in text:
            count_text = text.split("IDs 1 through ", 1)[1].split(")", 1)[0]
            count = int(count_text)
        else:
            count = 1
        system_content = cast(str, _as_object_dict(_as_object_list(payload["messages"])[0])["content"])
        prefix = "v2" if "Prompt V2" in system_content else "v1"
        return completion_response(
            content=json.dumps(
                {
                    "readings": [
                        {"id": i, "text": f"{prefix}-{i}"}
                        for i in range(1, count + 1)
                    ]
                }
            ),
            model="vlm-1",
        )

    RequestRecorder(respond).install(monkeypatch)
    cache = ProviderCache(InMemoryCacheStore())
    node = ReadTiffTextNode(open_page, cache=cache)
    source = Ref[TiffFile](
        artifact_id=artifact_id, artifact_type="file.tiff", schema_version=1
    )
    window = TiffPixelWindow(page=0, col=0, row=0, width=page_side, height=page_side)
    input_regions = TiffTextRegions(source=source, window=window, regions=regions)

    reader_v1 = VisionLlmCropTextReader(
        config=VisionLlmCropReaderConfig(
            system_prompt="Prompt V1",
            max_sheet_crops=10,
            max_concurrency=2,
        ),
        api_key=SecretStr(API_KEY),
        workspace_id=workspace_id,
        provider=VisionLlmCropReaderSdkProvider(),
    )
    first = await node.run(
        NodeExecutionContext(workspace_id=workspace_id),
        NoConfig(),
        RecognizeInput(regions=input_regions, recognizer=reader_v1),
    )
    # All 10 regions went in one wave and packed onto 1 contact sheet.
    assert call_count == 1
    assert [r.reading.text for r in first.text.regions if r.reading] == [
        f"v1-{i}" for i in range(1, 11)
    ]

    # Re-running with the same config hits ProviderCache completely.
    second_ctx = NodeExecutionContext(workspace_id=workspace_id)
    await node.run(
        second_ctx,
        NoConfig(),
        RecognizeInput(regions=input_regions, recognizer=reader_v1),
    )
    assert call_count == 1
    assert second_ctx.output_metadata == {"tiff_crops": 10, "tiff_cache_hits": 10}

    # Changing system_prompt busts the cache and runs a fresh sheet.
    reader_v2 = VisionLlmCropTextReader(
        config=VisionLlmCropReaderConfig(
            system_prompt="Prompt V2",
            max_sheet_crops=10,
            max_concurrency=2,
        ),
        api_key=SecretStr(API_KEY),
        workspace_id=workspace_id,
        provider=VisionLlmCropReaderSdkProvider(),
    )
    third = await node.run(
        NodeExecutionContext(workspace_id=workspace_id),
        NoConfig(),
        RecognizeInput(regions=input_regions, recognizer=reader_v2),
    )
    assert call_count == 2
    assert [r.reading.text for r in third.text.regions if r.reading] == [
        f"v2-{i}" for i in range(1, 11)
    ]


async def test_sdk_accepts_openrouter_gemini_response_extensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter responses with null finish_reason, non-OpenAI service_tier, and
    reasoning/cost extensions must not fail strict OpenAI ChatCompletion validation."""

    openrouter_payload = {
        "id": "gen-openrouter-1",
        "provider": "Google AI Studio",
        "model": "google/gemini-3.7-flash",
        "object": "chat.completion",
        "created": 1_786_640_581,
        "service_tier": "standard",
        "choices": [
            {
                "index": 0,
                "finish_reason": None,
                "native_finish_reason": "STOP",
                "logprobs": None,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"readings": [{"id": 1, "text": "Москва"}]}),
                    "refusal": None,
                    "reasoning": "Inspecting crop 1...",
                    "reasoning_details": [
                        {"type": "reasoning.text", "text": "Inspecting crop 1..."}
                    ],
                    "annotations": [
                        {"type": "url_citation", "url_citation": {"url": "https://example.com"}}
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": None,
            "total_tokens": 120,
            "cost": 0.0004,
        },
    }
    RequestRecorder(httpx.Response(200, json=openrouter_payload)).install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()
    readings = await provider.recognize(
        crops=[_crop_png()],
        config=VisionLlmCropReaderConfig(
            base_url="https://openrouter.ai/api/v1",
            model="google/gemini-3.7-flash",
        ),
        api_key=SecretStr(API_KEY),
        workspace_id=WORKSPACE_ID,
    )
    assert len(readings) == 1
    assert readings[0].text == "Москва"
    assert readings[0].model == "google/gemini-3.7-flash"


async def test_sdk_reports_openrouter_http_200_and_choice_errors_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = VisionLlmCropReaderSdkProvider()
    config = VisionLlmCropReaderConfig(
        base_url="https://openrouter.ai/api/v1",
        model="google/gemini-3.7-flash",
    )

    # Top-level HTTP 200 error payload from OpenRouter.
    RequestRecorder(
        httpx.Response(
            200,
            json={"error": {"code": 502, "message": f"upstream leak {API_KEY}"}},
        )
    ).install(monkeypatch)
    with pytest.raises(VisionLlmCropReaderError, match="HTTP 502") as top_err:
        await provider.recognize(
            crops=[_crop_png()],
            config=config,
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(top_err.value)
    assert "upstream leak" not in str(top_err.value)

    # Choice-level OpenRouter error (`finish_reason: "error"`).
    RequestRecorder(
        httpx.Response(
            200,
            json={
                "id": "gen-err-2",
                "model": "google/gemini-3.7-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "error",
                        "error": {"code": 503, "message": f"secret {API_KEY}"},
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
            },
        )
    ).install(monkeypatch)
    with pytest.raises(VisionLlmCropReaderError, match="HTTP 503") as choice_err:
        await provider.recognize(
            crops=[_crop_png()],
            config=config,
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
    assert API_KEY not in str(choice_err.value)
    assert "secret" not in str(choice_err.value)


async def test_sdk_reports_length_truncation_clearly_on_single_crop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RequestRecorder(
        httpx.Response(
            200,
            json={
                "id": "gen-len-1",
                "model": "google/gemini-3.7-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning": "ran out of token budget",
                        },
                    }
                ],
            },
        )
    ).install(monkeypatch)
    provider = VisionLlmCropReaderSdkProvider()
    with pytest.raises(VisionLlmCropReaderError, match="max_completion_tokens"):
        await provider.recognize(
            crops=[_crop_png()],
            config=VisionLlmCropReaderConfig(
                base_url="https://openrouter.ai/api/v1",
                model="google/gemini-3.7-flash",
            ),
            api_key=SecretStr(API_KEY),
            workspace_id=WORKSPACE_ID,
        )
