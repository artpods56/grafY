import json
from uuid import UUID, uuid4

import pytest
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from pydantic import SecretStr

import grafy_plugin.provider as provider_module
from grafy_core.artifacts import ArtifactRef, JsonObject
from grafy_plugin.processing import (
    ConversationMessage,
    MessageRole,
    ProviderSettings,
)
from grafy_plugin.provider import OpenAICompatibleStructuredProvider


class UnusedImageReader:
    async def filename(self, ref: ArtifactRef, *, workspace_id: UUID) -> str:
        del ref, workspace_id
        raise AssertionError("Provider test does not attach images")

    async def data_url(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
        remaining_total_bytes: int,
    ) -> tuple[str, int]:
        del ref, workspace_id, remaining_total_bytes
        raise AssertionError("Provider test does not attach images")


class FakeCompletions:
    def __init__(self, completion: ChatCompletion) -> None:
        self._completion = completion

    async def create(self, **request: object) -> ChatCompletion:
        del request
        return self._completion


class FakeChat:
    def __init__(self, completion: ChatCompletion) -> None:
        self.completions = FakeCompletions(completion)


class FakeAsyncOpenAI:
    completion: ChatCompletion

    def __init__(self, **configuration: object) -> None:
        del configuration
        self.chat = FakeChat(self.completion)

    async def __aenter__(self) -> "FakeAsyncOpenAI":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc_value, traceback


@pytest.mark.asyncio
async def test_provider_accepts_openai_compatible_service_tier_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_value: JsonObject = {"value": "extracted"}
    completion = ChatCompletion(
        id="completion-1",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                logprobs=None,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=json.dumps(structured_value),
                ),
            )
        ],
        created=1,
        model="compatible-model",
        object="chat.completion",
        service_tier="default",
    )
    object.__setattr__(completion, "service_tier", "provider-specific")
    FakeAsyncOpenAI.completion = completion
    monkeypatch.setattr(provider_module, "AsyncOpenAI", FakeAsyncOpenAI)

    schema = json.dumps(
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }
    )
    provider = OpenAICompatibleStructuredProvider(image_reader=UnusedImageReader())

    response = await provider.complete(
        [ConversationMessage(role=MessageRole.USER, text="Extract")],
        schema,
        ProviderSettings(
            base_url="https://provider.example/v1",
            model="compatible-model",
            temperature=0,
            max_completion_tokens=100,
            timeout_ms=1_000,
            max_retries=0,
            schema_name="result",
            strict=True,
        ),
        SecretStr("secret"),
        workspace_id=uuid4(),
    )

    assert response.structured_value == structured_value
    assert response.model == "compatible-model"


def _provider_settings() -> ProviderSettings:
    return ProviderSettings(
        base_url="https://provider.example/v1",
        model="compatible-model",
        temperature=0,
        max_completion_tokens=100,
        timeout_ms=1_000,
        max_retries=0,
        schema_name="result",
        strict=True,
    )


def _completion_with_content(content: str) -> ChatCompletion:
    return ChatCompletion(
        id="completion-1",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                logprobs=None,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=content,
                ),
            )
        ],
        created=1,
        model="compatible-model",
        object="chat.completion",
    )


@pytest.mark.asyncio
async def test_provider_omits_null_values_for_optional_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAsyncOpenAI.completion = _completion_with_content(
        json.dumps({"records": [{"name": "Abbey", "label": None}]})
    )
    monkeypatch.setattr(provider_module, "AsyncOpenAI", FakeAsyncOpenAI)

    schema = json.dumps(
        {
            "type": "object",
            "properties": {
                "records": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "label": {"type": "string"},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["records"],
            "additionalProperties": False,
        }
    )
    provider = OpenAICompatibleStructuredProvider(image_reader=UnusedImageReader())

    response = await provider.complete(
        [ConversationMessage(role=MessageRole.USER, text="Extract")],
        schema,
        _provider_settings(),
        SecretStr("secret"),
        workspace_id=uuid4(),
    )

    assert response.structured_value == {"records": [{"name": "Abbey"}]}
