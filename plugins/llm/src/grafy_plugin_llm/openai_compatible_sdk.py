import json
import os
from typing import Final, cast, final, override
from urllib.parse import urlparse
from uuid import UUID

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
    ChatCompletion,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.completion_create_params import (
    CompletionCreateParamsNonStreaming,
)
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import SecretStr, ValidationError

from grafy_core.artifacts import JsonObject, UnitOfWorkPort
from grafy_core.operators.prompts import PromptMessage, PromptMessageRole
from grafy_core.operators.schemas import (
    parse_json_schema,
    validate_json_schema_value,
)
from grafy_core.ports.storage import FileStoragePort

from grafy_plugin_llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    OpenAICompatibleProviderError,
    OpenAICompatibleProviderResponse,
)
from grafy_plugin_llm.prompt_images import (
    PromptImageDataError,
    PromptImageDataLoader,
)


OPENAI_COMPATIBLE_MAX_IMAGES: Final = 8
OPENAI_COMPATIBLE_MAX_IMAGE_BYTES: Final = 20_000_000
OPENAI_COMPATIBLE_MAX_TOTAL_IMAGE_BYTES: Final = 50_000_000
OPENAI_COMPATIBLE_SUPPORTED_IMAGE_CONTENT_TYPES: Final = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }
)


def _provider_status_guidance(
    status_code: int,
    *,
    base_url: str,
    model: str,
) -> str:
    if status_code == 400:
        return (
            "The provider rejected the request. Check whether the model "
            "supports the supplied messages, including images, and "
            "strict JSON Schema response formatting."
        )
    if status_code == 401:
        guidance = (
            "The provider did not accept the configured API key. The key must "
            "be issued by the API at the configured base URL."
        )
        host = (urlparse(base_url).hostname or "").lower()
        if host == "api.openai.com" and "/" in model:
            return (
                f"{guidance} Vendor-prefixed model ids are usually served by a "
                "gateway such as OpenRouter, not by api.openai.com."
            )
        return guidance
    if status_code == 402:
        return (
            "The provider requires additional credits or quota for this "
            "request."
        )
    if status_code == 403:
        return (
            "The configured API key does not have access to this model "
            "or endpoint."
        )
    if status_code == 404:
        return "Check that the base URL and model identifier are correct."
    if status_code == 408:
        return "The provider timed out while processing the request."
    if status_code == 429:
        return "The provider rate limit or account quota was exceeded."
    if 500 <= status_code <= 599:
        return (
            "The provider is currently unavailable or failed while "
            "processing the request."
        )
    return "The provider rejected the request."


@final
class OpenAICompatibleSdkProvider(OpenAICompatibleProvider):
    """OpenAI SDK adapter for compatible Chat Completions providers."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
    ) -> None:
        self._uow = uow
        self._storage = storage

    @override
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
        image_count = sum(len(message.image_refs) for message in messages)
        if image_count > OPENAI_COMPATIBLE_MAX_IMAGES:
            raise OpenAICompatibleProviderError(
                "OpenAI-compatible completion requests support at most "
                f"{OPENAI_COMPATIBLE_MAX_IMAGES} images, got {image_count}"
            )

        request_messages: list[ChatCompletionMessageParam] = []
        total_image_bytes = 0
        image_loader = PromptImageDataLoader(
            uow=self._uow,
            storage=self._storage,
            provider_title="OpenAI-compatible completions",
            max_image_bytes=OPENAI_COMPATIBLE_MAX_IMAGE_BYTES,
            max_total_image_bytes=OPENAI_COMPATIBLE_MAX_TOTAL_IMAGE_BYTES,
            supported_content_types=(
                OPENAI_COMPATIBLE_SUPPORTED_IMAGE_CONTENT_TYPES
            ),
        )
        for index, message in enumerate(messages):
            if message.role is PromptMessageRole.SYSTEM:
                if message.image_refs:
                    raise OpenAICompatibleProviderError(
                        f"System prompt message {index} cannot contain image refs"
                    )
                request_messages.append(
                    ChatCompletionSystemMessageParam(
                        role="system",
                        content=message.text,
                    )
                )
                continue
            if message.role is not PromptMessageRole.USER:
                raise OpenAICompatibleProviderError(
                    f"Unsupported prompt message role {message.role!r} at "
                    f"position {index}"
                )
            if not message.image_refs:
                request_messages.append(
                    ChatCompletionUserMessageParam(
                        role="user",
                        content=message.text,
                    )
                )
                continue

            content_parts: list[ChatCompletionContentPartParam] = [
                ChatCompletionContentPartTextParam(
                    type="text",
                    text=message.text,
                )
            ]
            for image_ref in message.image_refs:
                try:
                    image_url, image_bytes = await image_loader.data_url(
                        image_ref,
                        workspace_id=workspace_id,
                        remaining_total_bytes=(
                            OPENAI_COMPATIBLE_MAX_TOTAL_IMAGE_BYTES
                            - total_image_bytes
                        ),
                    )
                except PromptImageDataError as exc:
                    cause = exc.__cause__ if exc.__cause__ is not None else exc
                    raise OpenAICompatibleProviderError(str(exc)) from cause
                total_image_bytes += image_bytes
                content_parts.append(
                    ChatCompletionContentPartImageParam(
                        type="image_url",
                        image_url={"url": image_url},
                    )
                )
            request_messages.append(
                ChatCompletionUserMessageParam(
                    role="user",
                    content=content_parts,
                )
            )

        request: CompletionCreateParamsNonStreaming = {
            "model": config.model,
            "messages": request_messages,
            "temperature": config.temperature,
            "max_completion_tokens": config.max_completion_tokens,
        }
        if json_schema is not None:
            schema_object = parse_json_schema(
                json_schema,
                context=f"completion schema {config.schema_name!r}",
            )
            response_format: ResponseFormatJSONSchema = {
                "type": "json_schema",
                "json_schema": {
                    "name": config.schema_name,
                    "schema": schema_object,
                    "strict": config.strict,
                },
            }
            request["response_format"] = response_format

        endpoint = f"{config.base_url}/chat/completions"
        api_key_value = api_key.get_secret_value()
        custom_headers_env = os.environ.get("OPENAI_CUSTOM_HEADERS")
        safe_default_headers: dict[str, str | Omit] = {}
        if custom_headers_env is not None:
            for line in custom_headers_env.split("\n"):
                colon = line.find(":")
                if colon >= 0:
                    header_name = line[:colon].strip()
                    if header_name:
                        safe_default_headers[header_name] = Omit()
        safe_default_headers["OpenAI-Organization"] = Omit()
        safe_default_headers["OpenAI-Project"] = Omit()
        safe_default_headers["Authorization"] = f"Bearer {api_key_value}"

        try:
            async with DefaultAsyncHttpxClient(
                follow_redirects=False,
            ) as http_client:
                async with AsyncOpenAI(
                    api_key=api_key_value,
                    admin_api_key="",
                    organization="",
                    project="",
                    webhook_secret="",
                    base_url=config.base_url,
                    timeout=config.timeout_ms / 1_000,
                    max_retries=config.max_retries,
                    default_headers=cast(dict[str, str], safe_default_headers),
                    http_client=http_client,
                ) as client:
                    completion = await client.chat.completions.create(**request)
        except APITimeoutError:
            raise OpenAICompatibleProviderError(
                f"Chat Completions request to {endpoint!r} timed out for model "
                f"{config.model!r}"
            ) from None
        except APIStatusError as exc:
            guidance = _provider_status_guidance(
                exc.status_code,
                base_url=config.base_url,
                model=config.model,
            )
            raise OpenAICompatibleProviderError(
                f"Chat Completions request to {endpoint!r} returned HTTP "
                f"{exc.status_code} for model {config.model!r}. {guidance}"
            ) from None
        except APIConnectionError:
            raise OpenAICompatibleProviderError(
                f"Chat Completions request to {endpoint!r} could not connect for "
                f"model {config.model!r}"
            ) from None
        except APIResponseValidationError:
            raise OpenAICompatibleProviderError(
                f"Chat Completions response from {endpoint!r} did not match the "
                f"SDK response model for {config.model!r}"
            ) from None
        except OpenAIError as exc:
            raise OpenAICompatibleProviderError(
                f"Chat Completions request to {endpoint!r} failed for model "
                f"{config.model!r} with {exc.__class__.__name__}"
            ) from None

        try:
            completion = ChatCompletion.model_validate(completion.model_dump())
        except ValidationError:
            raise OpenAICompatibleProviderError(
                f"Chat Completions response from {endpoint!r} did not match the "
                f"SDK response model for {config.model!r}"
            ) from None

        if not completion.choices:
            raise OpenAICompatibleProviderError(
                f"Chat Completions response from {endpoint!r} contained no choices "
                f"for model {config.model!r}"
            )

        choice = completion.choices[0]
        if choice.message.refusal is not None and choice.message.refusal != "":
            raise OpenAICompatibleProviderError(
                f"Chat Completions choice {choice.index} was refused for model "
                f"{config.model!r}"
            )
        assistant_content = choice.message.content
        if assistant_content is None:
            raise OpenAICompatibleProviderError(
                f"Chat Completions choice {choice.index} did not contain text for "
                f"model {config.model!r}"
            )

        structured_value: JsonObject | None = None
        if json_schema is not None:
            try:
                structured_json: object = json.loads(assistant_content)
            except json.JSONDecodeError:
                raise OpenAICompatibleProviderError(
                    f"Chat Completions choice {choice.index} returned invalid JSON "
                    f"for schema {config.schema_name!r} and model {config.model!r}"
                ) from None
            if not isinstance(structured_json, dict):
                raise OpenAICompatibleProviderError(
                    f"Chat Completions choice {choice.index} JSON must be an object "
                    f"for schema {config.schema_name!r} and model {config.model!r}"
                )
            try:
                structured_value = validate_json_schema_value(
                    json_schema,
                    cast(JsonObject, structured_json),
                )
            except Exception:
                raise OpenAICompatibleProviderError(
                    f"Chat Completions choice {choice.index} JSON did not match "
                    f"schema {config.schema_name!r} for model {config.model!r}"
                ) from None

        safe_usage: JsonObject = {}
        if completion.usage is not None:
            safe_usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
        return OpenAICompatibleProviderResponse(
            content=assistant_content,
            structured_value=structured_value,
            model=completion.model,
            response_id=completion.id,
            finish_reason=choice.finish_reason,
            usage=safe_usage,
        )
