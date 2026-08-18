import json
from collections.abc import AsyncIterator, Callable
from io import BytesIO
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from grafy_core.artifacts import (
    ArtifactObject,
    InMemoryUnitOfWork,
    JsonObject,
)
from grafy_core.operators.images import RASTER_IMAGE
from grafy_core.operators.prompts import PromptMessage, PromptMessageRole
from grafy_core.ports.storage import SaveFileCommand, StoredFile, StoredObjectInfo
from grafy_plugin_llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProviderError,
)
from grafy_plugin_llm.openai_compatible_sdk import (
    OPENAI_COMPATIBLE_MAX_IMAGES,
    OpenAICompatibleSdkProvider,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000902")


class RequestRecorder:
    def __init__(
        self,
        response: httpx.Response | Callable[[httpx.Request], httpx.Response],
    ) -> None:
        self._response = response
        self.requests: list[httpx.Request] = []
        self.clients: list[httpx.AsyncClient] = []
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
        self,
        client: httpx.AsyncClient,
        request: httpx.Request,
    ) -> httpx.Response:
        self.requests.append(request)
        self.clients.append(client)
        self.client_follow_redirects.append(client.follow_redirects)
        if callable(self._response):
            response = self._response(request)
        else:
            response = self._response
        response.request = request
        return response


class StaticAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._content


class TransportRequestRecorder:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.requests: list[httpx.Request] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        async def handle_async_request(
            transport: httpx.AsyncHTTPTransport,
            request: httpx.Request,
        ) -> httpx.Response:
            del transport
            recorder.requests.append(request)
            return httpx.Response(
                status_code=recorder._response.status_code,
                headers=recorder._response.headers,
                stream=StaticAsyncByteStream(recorder._response.content),
                request=request,
            )

        monkeypatch.setattr(
            httpx.AsyncHTTPTransport,
            "handle_async_request",
            handle_async_request,
        )


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.load_calls: list[tuple[str, str]] = []

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
        self.load_calls.append((bucket, path))
        return BytesIO(self.files[(bucket, path)])

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

    def exists(self, bucket: str, path: str) -> bool:
        return (bucket, path) in self.files


def sdk_provider(
    monkeypatch: pytest.MonkeyPatch,
    recorder: RequestRecorder,
    *,
    uow: InMemoryUnitOfWork | None = None,
    storage: FakeStorage | None = None,
) -> OpenAICompatibleSdkProvider:
    recorder.install(monkeypatch)
    return OpenAICompatibleSdkProvider(
        uow=InMemoryUnitOfWork() if uow is None else uow,
        storage=FakeStorage() if storage is None else storage,
    )


async def add_stored_image(
    uow: InMemoryUnitOfWork,
    storage: FakeStorage,
    *,
    name: str,
    workspace_id: UUID,
    content: bytes = b"image-bytes",
) -> ArtifactObject:
    image = ArtifactObject(
        workspace_id=workspace_id,
        id=uuid4(),
        artifact_type=RASTER_IMAGE.key.id,
        schema_version=RASTER_IMAGE.key.schema_version,
        content_type="image/png",
        bucket="artifacts",
        object_key=f"images/{name}.png",
        byte_size=len(content),
    )
    storage.files[("artifacts", f"images/{name}.png")] = content
    async with uow as transaction:
        await transaction.artifacts.add(image)
        await transaction.commit()
    return image


def object_schema() -> str:
    return (
        '{"type":"object","properties":{"invoice_number":{"type":"string"}},'
        '"required":["invoice_number"],"additionalProperties":false}'
    )


def completion_response(
    *,
    content: str = "A concise answer.",
    refusal: str | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-123",
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
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 4,
                "total_tokens": 16,
                "provider_debug": {
                    "authorization": "Bearer secret-provider-key"
                },
            },
        },
    )


def timeout_response(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout(
        "transport included secret-provider-key",
        request=request,
    )


def connection_error_response(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(
        "transport included secret-provider-key",
        request=request,
    )


def test_config_normalizes_secure_and_local_base_urls() -> None:
    assert OpenAICompatibleConfig().max_retries == 0
    assert (
        OpenAICompatibleConfig(base_url="https://Example.COM/v1/").base_url
        == "https://example.com/v1"
    )
    assert (
        OpenAICompatibleConfig(base_url="http://localhost:4000/v1/").base_url
        == "http://localhost:4000/v1"
    )
    assert (
        OpenAICompatibleConfig(base_url="http://127.0.0.42:4000/v1").base_url
        == "http://127.0.0.42:4000/v1"
    )
    assert (
        OpenAICompatibleConfig(base_url="http://[::1]:4000/v1").base_url
        == "http://[::1]:4000/v1"
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
def test_config_rejects_base_urls_that_could_expose_credentials(
    base_url: str,
) -> None:
    with pytest.raises(ValidationError):
        OpenAICompatibleConfig(base_url=base_url)


@pytest.mark.parametrize("max_retries", [-1, 6])
def test_config_bounds_sdk_retries(max_retries: int) -> None:
    with pytest.raises(ValidationError):
        OpenAICompatibleConfig(max_retries=max_retries)


async def test_provider_posts_text_chat_completion_with_bearer_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(completion_response())
    provider = sdk_provider(monkeypatch, recorder)
    config = OpenAICompatibleConfig(
        base_url="https://gateway.example/v1/",
        model="openai/gpt-compatible",
        temperature=0.25,
        max_completion_tokens=777,
        timeout_ms=42_000,
    )

    result = await provider.complete(
        [
            PromptMessage(
                role=PromptMessageRole.SYSTEM,
                text="Answer precisely.",
            ),
            PromptMessage(
                role=PromptMessageRole.USER,
                text="What is 6 times 7?",
            ),
        ],
        None,
        config,
        SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    assert len(recorder.requests) == 1
    assert recorder.client_follow_redirects == [False]
    assert recorder.clients[0].is_closed
    request = recorder.requests[0]
    assert str(request.url) == "https://gateway.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret-provider-key"
    assert json.loads(request.content) == {
        "model": "openai/gpt-compatible",
        "messages": [
            {"role": "system", "content": "Answer precisely."},
            {"role": "user", "content": "What is 6 times 7?"},
        ],
        "temperature": 0.25,
        "max_completion_tokens": 777,
    }
    assert result.model_dump(mode="json") == {
        "content": "A concise answer.",
        "structured_value": None,
        "model": "provider-model-2026-01",
        "response_id": "chatcmpl-123",
        "finish_reason": "stop",
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 4,
            "total_tokens": 16,
        },
    }


async def test_provider_requests_and_validates_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(
        completion_response(content='{"invoice_number":"FV/42"}')
    )
    provider = sdk_provider(monkeypatch, recorder)
    config = OpenAICompatibleConfig(
        model="structured-model",
        schema_name="invoice",
        strict=True,
    )
    schema = object_schema()

    result = await provider.complete(
        [
            PromptMessage(
                role=PromptMessageRole.USER,
                text="Extract the invoice number.",
            )
        ],
        schema,
        config,
        SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    request_payload = cast(JsonObject, json.loads(recorder.requests[0].content))
    assert request_payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "invoice",
            "schema": {
                "type": "object",
                "properties": {"invoice_number": {"type": "string"}},
                "required": ["invoice_number"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
    assert result.content == '{"invoice_number":"FV/42"}'
    assert result.structured_value == {"invoice_number": "FV/42"}


async def test_provider_rejects_a_structured_value_that_misses_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = sdk_provider(
        monkeypatch,
        RequestRecorder(completion_response(content='{"wrong":"value"}'))
    )

    with pytest.raises(
        OpenAICompatibleProviderError,
        match="did not match schema 'structured_response'.*gpt-4.1-mini",
    ) as captured:
        await provider.complete(
            [
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Extract it.",
                )
            ],
            object_schema(),
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert captured.value.__cause__ is None


async def test_provider_reports_refusal_without_exposing_refusal_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal_text = "private refusal details"
    provider = sdk_provider(
        monkeypatch,
        RequestRecorder(completion_response(content="", refusal=refusal_text))
    )

    with pytest.raises(OpenAICompatibleProviderError, match="was refused") as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert refusal_text not in str(captured.value)


async def test_provider_does_not_follow_redirects_with_a_bearer_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(
        httpx.Response(
            307,
            headers={"Location": "https://attacker.example/chat/completions"},
        )
    )
    provider = sdk_provider(monkeypatch, recorder)

    with pytest.raises(OpenAICompatibleProviderError, match="HTTP 307"):
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert len(recorder.requests) == 1
    assert recorder.requests[0].url.host == "api.openai.com"
    assert recorder.client_follow_redirects == [False]


async def test_provider_error_never_contains_response_body_or_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "secret-provider-key"
    echoed_body = f"provider echoed {api_key} in an error"
    recorder = RequestRecorder(httpx.Response(500, text=echoed_body))
    provider = sdk_provider(monkeypatch, recorder)

    with pytest.raises(OpenAICompatibleProviderError, match="HTTP 500") as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(),
            SecretStr(api_key),
            workspace_id=WORKSPACE_ID,
        )

    assert api_key not in str(captured.value)
    assert echoed_body not in str(captured.value)
    assert captured.value.__cause__ is None
    assert len(recorder.requests) == 1
    assert recorder.clients[0].is_closed


@pytest.mark.parametrize(
    ("status_code", "expected_guidance"),
    [
        (400, "supplied messages, including images.*strict JSON Schema"),
        (401, "configured API key.*base URL.*OpenRouter"),
        (402, "additional credits or quota"),
        (403, "does not have access"),
        (404, "base URL and model identifier"),
        (408, "timed out"),
        (429, "rate limit or account quota"),
        (503, "provider is currently unavailable"),
    ],
)
async def test_provider_status_errors_include_safe_actionable_guidance(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_guidance: str,
) -> None:
    api_key = "secret-provider-key"
    echoed_body = f"provider echoed {api_key} in an error"
    provider = sdk_provider(
        monkeypatch,
        RequestRecorder(httpx.Response(status_code, text=echoed_body)),
    )

    with pytest.raises(
        OpenAICompatibleProviderError,
        match=expected_guidance,
    ) as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            object_schema(),
            OpenAICompatibleConfig(model="provider/model"),
            SecretStr(api_key),
            workspace_id=WORKSPACE_ID,
        )

    message = str(captured.value)
    assert f"HTTP {status_code}" in message
    assert "provider/model" in message
    assert api_key not in message
    assert echoed_body not in message
    assert captured.value.__cause__ is None


async def test_provider_401_on_openai_host_hints_gateway_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = sdk_provider(
        monkeypatch,
        RequestRecorder(httpx.Response(401, text="unauthorized")),
    )

    with pytest.raises(OpenAICompatibleProviderError) as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(model="openai/gpt-5.6-luna"),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    message = str(captured.value)
    assert "HTTP 401" in message
    assert "https://api.openai.com/v1/chat/completions" in message
    assert "openai/gpt-5.6-luna" in message
    assert "issued by the API at the configured base URL" in message
    assert "OpenRouter" in message
    assert captured.value.__cause__ is None


async def test_provider_401_on_custom_host_does_not_assume_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = sdk_provider(
        monkeypatch,
        RequestRecorder(httpx.Response(401, text="unauthorized")),
    )

    with pytest.raises(OpenAICompatibleProviderError) as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(
                base_url="https://openrouter.ai/api/v1",
                model="openai/gpt-4o",
            ),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    message = str(captured.value)
    assert "HTTP 401" in message
    assert "https://openrouter.ai/api/v1/chat/completions" in message
    assert "issued by the API at the configured base URL" in message
    assert "OpenRouter" not in message
    assert captured.value.__cause__ is None


async def test_provider_401_on_openai_host_without_vendor_prefix_omits_gateway_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = sdk_provider(
        monkeypatch,
        RequestRecorder(httpx.Response(401, text="unauthorized")),
    )

    with pytest.raises(OpenAICompatibleProviderError) as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(model="gpt-4.1-mini"),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    message = str(captured.value)
    assert "issued by the API at the configured base URL" in message
    assert "OpenRouter" not in message
    assert captured.value.__cause__ is None


async def test_provider_does_not_forward_openai_server_environment_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "server-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "server-project")
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS",
        "aUtHoRiZaTiOn: Bearer server-environment-key\n"
        "X-Server-Secret: private-server-header",
    )
    recorder = TransportRequestRecorder(completion_response())
    recorder.install(monkeypatch)
    provider = OpenAICompatibleSdkProvider(
        uow=InMemoryUnitOfWork(),
        storage=FakeStorage(),
    )

    result = await provider.complete(
        [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
        None,
        OpenAICompatibleConfig(),
        SecretStr("graph-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    assert result.content == "A concise answer."
    assert len(recorder.requests) == 1
    request_headers = recorder.requests[0].headers
    assert request_headers["Authorization"] == "Bearer graph-provider-key"
    assert "X-Server-Secret" not in request_headers
    assert "OpenAI-Organization" not in request_headers
    assert "OpenAI-Project" not in request_headers
    assert "server-environment-key" not in str(request_headers)
    assert "private-server-header" not in str(request_headers)


async def test_provider_sanitizes_sdk_timeout_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(timeout_response)
    provider = sdk_provider(monkeypatch, recorder)

    with pytest.raises(OpenAICompatibleProviderError, match="timed out") as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert "secret-provider-key" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert len(recorder.requests) == 1
    assert recorder.clients[0].is_closed


async def test_provider_sanitizes_sdk_connection_error_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(connection_error_response)
    provider = sdk_provider(monkeypatch, recorder)

    with pytest.raises(
        OpenAICompatibleProviderError,
        match="could not connect",
    ) as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert "secret-provider-key" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert len(recorder.requests) == 1
    assert recorder.clients[0].is_closed


async def test_provider_rejects_malformed_sdk_response_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(
        httpx.Response(
            200,
            json={
                "id": "chatcmpl-malformed",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "provider-model-2026-01",
            },
        )
    )
    provider = sdk_provider(monkeypatch, recorder)

    with pytest.raises(
        OpenAICompatibleProviderError,
        match="did not match the SDK response model",
    ) as captured:
        await provider.complete(
            [PromptMessage(role=PromptMessageRole.USER, text="Complete it.")],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert captured.value.__cause__ is None
    assert recorder.clients[0].is_closed


async def test_provider_sends_verified_images_as_openai_content_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = InMemoryUnitOfWork()
    storage = FakeStorage()
    image = await add_stored_image(
        uow, storage, name="page", workspace_id=WORKSPACE_ID
    )
    recorder = RequestRecorder(completion_response())
    provider = sdk_provider(
        monkeypatch,
        recorder,
        uow=uow,
        storage=storage,
    )

    await provider.complete(
        [
            PromptMessage(
                role=PromptMessageRole.USER,
                text="Read the image.",
                image_refs=[image.ref()],
            )
        ],
        None,
        OpenAICompatibleConfig(),
        SecretStr("secret-provider-key"),
        workspace_id=WORKSPACE_ID,
    )

    request_payload = cast(JsonObject, json.loads(recorder.requests[0].content))
    assert request_payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read the image."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,aW1hZ2UtYnl0ZXM="
                    },
                },
            ],
        }
    ]


async def test_provider_rejects_foreign_workspace_image_before_storage_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = InMemoryUnitOfWork()
    storage = FakeStorage()
    image = await add_stored_image(
        uow, storage, name="private", workspace_id=WORKSPACE_ID
    )
    recorder = RequestRecorder(completion_response())
    provider = sdk_provider(
        monkeypatch,
        recorder,
        uow=uow,
        storage=storage,
    )

    with pytest.raises(
        OpenAICompatibleProviderError,
        match=f"Prompt image artifact {image.id} was not found",
    ):
        await provider.complete(
            [
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Read the image.",
                    image_refs=[image.ref()],
                )
            ],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=OTHER_WORKSPACE_ID,
        )

    assert storage.load_calls == []
    assert recorder.requests == []


async def test_provider_enforces_image_count_before_loading_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RequestRecorder(completion_response())
    provider = sdk_provider(monkeypatch, recorder)
    image_refs = [
        ArtifactObject(
            workspace_id=WORKSPACE_ID,
            id=uuid4(),
            artifact_type=RASTER_IMAGE.key.id,
            schema_version=RASTER_IMAGE.key.schema_version,
            content_type="image/png",
        ).ref()
        for _ in range(OPENAI_COMPATIBLE_MAX_IMAGES + 1)
    ]

    with pytest.raises(OpenAICompatibleProviderError, match="at most 8 images"):
        await provider.complete(
            [
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Read all images.",
                    image_refs=image_refs,
                )
            ],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert recorder.requests == []


async def test_provider_enforces_aggregate_image_limit_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "grafy_plugin_llm.openai_compatible_sdk."
        "OPENAI_COMPATIBLE_MAX_TOTAL_IMAGE_BYTES",
        8,
    )
    uow = InMemoryUnitOfWork()
    storage = FakeStorage()
    first = await add_stored_image(
        uow,
        storage,
        name="first",
        workspace_id=WORKSPACE_ID,
        content=b"12345",
    )
    second = await add_stored_image(
        uow,
        storage,
        name="second",
        workspace_id=WORKSPACE_ID,
        content=b"67890",
    )
    recorder = RequestRecorder(completion_response())
    provider = sdk_provider(
        monkeypatch,
        recorder,
        uow=uow,
        storage=storage,
    )

    with pytest.raises(
        OpenAICompatibleProviderError,
        match=f"aggregate limit at artifact {second.id}",
    ):
        await provider.complete(
            [
                PromptMessage(
                    role=PromptMessageRole.USER,
                    text="Read both images.",
                    image_refs=[first.ref(), second.ref()],
                )
            ],
            None,
            OpenAICompatibleConfig(),
            SecretStr("secret-provider-key"),
            workspace_id=WORKSPACE_ID,
        )

    assert recorder.requests == []
