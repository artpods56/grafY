from dataclasses import dataclass
from typing import Protocol, cast, final, override

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
    Omit,
    OpenAIError,
)
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.completion_create_params import (
    CompletionCreateParamsNonStreaming,
)
from pydantic import SecretStr

from grafy_plugin.processing import SYSTEM_PROMPT


TRANSIENT_HTTP_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ClassificationProviderError(RuntimeError):
    """A provider failure whose message is safe to show to graph users."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    base_url: str
    model: str
    temperature: float
    max_completion_tokens: int
    timeout_ms: int


class ClassificationProvider(Protocol):
    async def complete(
        self,
        prompt: str,
        settings: ProviderSettings,
        api_key: SecretStr,
    ) -> str: ...


@final
class OpenAICompatibleClassificationProvider(ClassificationProvider):
    @override
    async def complete(
        self,
        prompt: str,
        settings: ProviderSettings,
        api_key: SecretStr,
    ) -> str:
        request: CompletionCreateParamsNonStreaming = {
            "model": settings.model,
            "messages": [
                ChatCompletionSystemMessageParam(role="system", content=SYSTEM_PROMPT),
                ChatCompletionUserMessageParam(role="user", content=prompt),
            ],
            "temperature": settings.temperature,
            "max_completion_tokens": settings.max_completion_tokens,
            "response_format": {"type": "json_object"},
        }
        endpoint = f"{settings.base_url}/chat/completions"
        api_key_value = api_key.get_secret_value()
        safe_headers: dict[str, str | Omit] = {
            "OpenAI-Organization": Omit(),
            "OpenAI-Project": Omit(),
            "Authorization": f"Bearer {api_key_value}",
        }
        try:
            async with DefaultAsyncHttpxClient(follow_redirects=False) as http_client:
                async with AsyncOpenAI(
                    api_key=api_key_value,
                    admin_api_key="",
                    organization="",
                    project="",
                    webhook_secret="",
                    base_url=settings.base_url,
                    timeout=settings.timeout_ms / 1_000,
                    max_retries=0,
                    default_headers=cast(dict[str, str], safe_headers),
                    http_client=http_client,
                ) as client:
                    completion = await client.chat.completions.create(**request)
        except APITimeoutError:
            raise ClassificationProviderError(
                f"Request to {endpoint!r} timed out for model {settings.model!r}",
                transient=True,
            ) from None
        except APIStatusError as exc:
            raise ClassificationProviderError(
                f"Request to {endpoint!r} returned HTTP {exc.status_code} for "
                f"model {settings.model!r}",
                transient=exc.status_code in TRANSIENT_HTTP_CODES,
            ) from None
        except APIConnectionError:
            raise ClassificationProviderError(
                f"Could not connect to {endpoint!r} for model {settings.model!r}",
                transient=True,
            ) from None
        except APIResponseValidationError:
            raise ClassificationProviderError(
                f"Response from {endpoint!r} did not match the provider SDK model"
            ) from None
        except OpenAIError as exc:
            raise ClassificationProviderError(
                f"Request to {endpoint!r} failed with {exc.__class__.__name__}"
            ) from None

        if not completion.choices:
            raise ClassificationProviderError(
                f"Response from {endpoint!r} contained no choices",
                transient=True,
            )
        choice = completion.choices[0]
        if choice.message.refusal:
            raise ClassificationProviderError(
                f"Provider refused classification for model {settings.model!r}"
            )
        if choice.message.content is None or choice.message.content.strip() == "":
            raise ClassificationProviderError(
                f"Provider returned no content for model {settings.model!r}",
                transient=True,
            )
        return choice.message.content
