import base64
from collections.abc import Sequence
from hashlib import sha256
import json
import os
from typing import Final, Protocol, cast, final, override
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
    ChatCompletionAssistantMessageParam,
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
from pydantic import SecretStr

from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import ArtifactObject, ArtifactRef, JsonObject
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.schema_contracts import (
    parse_json_schema,
    validate_json_schema_value,
)

from grafy_plugin.processing import (
    ConversationMessage,
    MessageRole,
    ProviderResponse,
    ProviderSettings,
    StructuredCompletionError,
    StructuredCompletionProvider,
)


MAX_IMAGE_BYTES: Final = 20_000_000
MAX_TOTAL_IMAGE_BYTES: Final = 50_000_000
SUPPORTED_IMAGE_CONTENT_TYPES: Final = frozenset(
    {"image/gif", "image/jpeg", "image/jpg", "image/png", "image/webp"}
)


def _schema_types(schema: dict[str, object]) -> set[object]:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return set(cast(list[object], schema_type))
    if schema_type is None:
        return set()
    return {schema_type}


def _omit_null_optional_properties(
    schema: dict[str, object],
    value: object,
) -> object:
    types = _schema_types(schema)
    omitted: object = value
    if "object" in types and isinstance(value, dict):
        raw_required = schema.get("required")
        required: set[str] = set()
        if isinstance(raw_required, list):
            required = {
                item
                for item in cast(list[object], raw_required)
                if isinstance(item, str)
            }
        raw_properties = schema.get("properties")
        properties = (
            cast(dict[object, object], raw_properties)
            if isinstance(raw_properties, dict)
            else {}
        )
        cleaned: dict[str, object] = {}
        for raw_key, item in cast(dict[object, object], value).items():
            if not isinstance(raw_key, str):
                continue
            if item is None and raw_key not in required:
                continue
            property_schema = properties.get(raw_key)
            if isinstance(property_schema, dict):
                cleaned[raw_key] = _omit_null_optional_properties(
                    cast(dict[str, object], property_schema),
                    item,
                )
            else:
                cleaned[raw_key] = item
        omitted = cleaned
    elif "array" in types and isinstance(value, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            item_schema = cast(dict[str, object], items_schema)
            cleaned_items: list[object] = []
            for item in cast(list[object], value):
                cleaned_items.append(_omit_null_optional_properties(item_schema, item))
            omitted = cleaned_items
    return omitted


class StructuredExtractionProviderError(StructuredCompletionError):
    """A bounded provider failure safe to present to a graph user."""


class ImageSourceReader(Protocol):
    async def filename(self, ref: ArtifactRef, *, workspace_id: UUID) -> str: ...

    async def data_url(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
        remaining_total_bytes: int,
    ) -> tuple[str, int]: ...


class RasterArtifactReader(ImageSourceReader):
    def __init__(self, *, uow: UnitOfWorkPort, storage: FileStoragePort) -> None:
        self._uow = uow
        self._storage = storage

    async def filename(self, ref: ArtifactRef, *, workspace_id: UUID) -> str:
        artifact = await self._artifact(ref, workspace_id=workspace_id)
        filename = artifact.metadata.get("original_filename")
        if isinstance(filename, str) and filename.strip() != "":
            return filename
        return str(ref.artifact_id)

    async def data_url(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
        remaining_total_bytes: int,
    ) -> tuple[str, int]:
        artifact = await self._artifact(ref, workspace_id=workspace_id)
        if artifact.bucket is None or artifact.object_key is None:
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} does not have a storage object"
            )
        if artifact.content_type not in SUPPORTED_IMAGE_CONTENT_TYPES:
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} has unsupported content type "
                f"{artifact.content_type!r}"
            )
        if artifact.byte_size is not None and artifact.byte_size > MAX_IMAGE_BYTES:
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} exceeds the "
                f"{MAX_IMAGE_BYTES}-byte limit"
            )
        if (
            artifact.byte_size is not None
            and artifact.byte_size > remaining_total_bytes
        ):
            raise StructuredExtractionProviderError(
                f"Images exceed the {MAX_TOTAL_IMAGE_BYTES}-byte request limit"
            )

        try:
            stream = await self._storage.load(
                bucket=artifact.bucket,
                path=artifact.object_key,
            )
            try:
                read_limit = min(MAX_IMAGE_BYTES, remaining_total_bytes)
                image_bytes = stream.read(read_limit + 1)
            finally:
                stream.close()
        except Exception as exc:
            raise StructuredExtractionProviderError(
                f"Failed to load image artifact {ref.artifact_id}"
            ) from exc

        actual_size = len(image_bytes)
        if actual_size > MAX_IMAGE_BYTES or actual_size > remaining_total_bytes:
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} exceeds request limits"
            )
        if artifact.byte_size is not None and actual_size != artifact.byte_size:
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} size does not match metadata"
            )
        actual_sha256 = sha256(image_bytes).hexdigest()
        expected_hashes = {
            value for value in (artifact.sha256, ref.content_hash) if value is not None
        }
        if any(value != actual_sha256 for value in expected_hashes):
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} SHA-256 does not match metadata"
            )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{artifact.content_type};base64,{encoded}", actual_size

    async def _artifact(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
    ) -> ArtifactObject:
        if ref.key() != RASTER_IMAGE.key:
            raise StructuredExtractionProviderError(
                f"Expected {RASTER_IMAGE.key.id}@{RASTER_IMAGE.key.schema_version}, "
                f"got {ref.artifact_type}@{ref.schema_version}"
            )
        try:
            async with self._uow as uow:
                artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        except Exception as exc:
            raise StructuredExtractionProviderError(
                f"Failed to look up image artifact {ref.artifact_id}"
            ) from exc
        if artifact is None:
            raise StructuredExtractionProviderError(
                f"Image artifact {ref.artifact_id} was not found"
            )
        if artifact.ref() != ref:
            raise StructuredExtractionProviderError(
                f"Repository returned a different ref for image {ref.artifact_id}"
            )
        return artifact


@final
class OpenAICompatibleStructuredProvider(StructuredCompletionProvider):
    def __init__(self, *, image_reader: ImageSourceReader) -> None:
        self._image_reader = image_reader

    @override
    async def complete(
        self,
        messages: Sequence[ConversationMessage],
        json_schema: str,
        settings: ProviderSettings,
        api_key: SecretStr,
        *,
        workspace_id: UUID,
    ) -> ProviderResponse:
        request_messages: list[ChatCompletionMessageParam] = []
        total_image_bytes = 0
        for message in messages:
            if message.role is MessageRole.SYSTEM:
                request_messages.append(
                    ChatCompletionSystemMessageParam(
                        role="system",
                        content=message.text,
                    )
                )
                continue
            if message.role is MessageRole.ASSISTANT:
                request_messages.append(
                    ChatCompletionAssistantMessageParam(
                        role="assistant",
                        content=message.text,
                    )
                )
                continue
            if not message.image_refs:
                request_messages.append(
                    ChatCompletionUserMessageParam(
                        role="user",
                        content=message.text,
                    )
                )
                continue

            content_parts: list[ChatCompletionContentPartParam] = [
                ChatCompletionContentPartTextParam(type="text", text=message.text)
            ]
            for image_ref in message.image_refs:
                image_url, image_bytes = await self._image_reader.data_url(
                    image_ref,
                    workspace_id=workspace_id,
                    remaining_total_bytes=MAX_TOTAL_IMAGE_BYTES - total_image_bytes,
                )
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

        schema_object = parse_json_schema(
            json_schema,
            context=f"structured extraction schema {settings.schema_name!r}",
        )
        response_format: ResponseFormatJSONSchema = {
            "type": "json_schema",
            "json_schema": {
                "name": settings.schema_name,
                "schema": schema_object,
                "strict": settings.strict,
            },
        }
        request: CompletionCreateParamsNonStreaming = {
            "model": settings.model,
            "messages": request_messages,
            "temperature": settings.temperature,
            "max_completion_tokens": settings.max_completion_tokens,
            "response_format": response_format,
        }
        endpoint = f"{settings.base_url}/chat/completions"
        safe_headers: dict[str, str | Omit] = {
            "OpenAI-Organization": Omit(),
            "OpenAI-Project": Omit(),
            "Authorization": f"Bearer {api_key.get_secret_value()}",
        }
        custom_headers = os.environ.get("OPENAI_CUSTOM_HEADERS")
        if custom_headers is not None:
            for line in custom_headers.split("\n"):
                name, separator, _value = line.partition(":")
                if separator and name.strip():
                    safe_headers[name.strip()] = Omit()

        try:
            async with DefaultAsyncHttpxClient(follow_redirects=False) as http_client:
                async with AsyncOpenAI(
                    api_key=api_key.get_secret_value(),
                    admin_api_key="",
                    organization="",
                    project="",
                    webhook_secret="",
                    base_url=settings.base_url,
                    timeout=settings.timeout_ms / 1_000,
                    max_retries=settings.max_retries,
                    default_headers=cast(dict[str, str], safe_headers),
                    http_client=http_client,
                ) as client:
                    completion = await client.chat.completions.create(**request)
        except APITimeoutError:
            raise StructuredExtractionProviderError(
                f"Request to {endpoint!r} timed out for model {settings.model!r}"
            ) from None
        except APIStatusError as exc:
            raise StructuredExtractionProviderError(
                f"Request to {endpoint!r} returned HTTP {exc.status_code} for "
                f"model {settings.model!r}"
            ) from None
        except APIConnectionError:
            raise StructuredExtractionProviderError(
                f"Could not connect to {endpoint!r} for model {settings.model!r}"
            ) from None
        except APIResponseValidationError:
            raise StructuredExtractionProviderError(
                f"Response from {endpoint!r} did not match the provider SDK model"
            ) from None
        except OpenAIError as exc:
            raise StructuredExtractionProviderError(
                f"Request to {endpoint!r} failed with {exc.__class__.__name__}"
            ) from None

        if not completion.choices:
            raise StructuredExtractionProviderError(
                f"Response from {endpoint!r} contained no choices"
            )
        choice = completion.choices[0]
        if choice.message.refusal:
            raise StructuredExtractionProviderError(
                f"Provider refused structured extraction for model {settings.model!r}"
            )
        if choice.message.content is None:
            raise StructuredExtractionProviderError(
                f"Provider returned no content for model {settings.model!r}"
            )
        try:
            raw_value: object = json.loads(choice.message.content)
        except json.JSONDecodeError:
            raise StructuredExtractionProviderError(
                f"Provider returned invalid JSON for model {settings.model!r}"
            ) from None
        if not isinstance(raw_value, dict):
            raise StructuredExtractionProviderError(
                f"Provider JSON must be an object for model {settings.model!r}"
            )
        omitted = _omit_null_optional_properties(
            schema_object,
            cast(JsonObject, raw_value),
        )
        if not isinstance(omitted, dict):
            raise StructuredExtractionProviderError(
                f"Provider JSON must be an object for model {settings.model!r}"
            )
        try:
            structured_value = validate_json_schema_value(
                json_schema,
                cast(JsonObject, omitted),
            )
        except ValueError as exc:
            raise StructuredExtractionProviderError(str(exc)) from exc

        usage: JsonObject = {}
        if completion.usage is not None:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
        return ProviderResponse(
            content=choice.message.content,
            structured_value=structured_value,
            model=completion.model,
            response_id=completion.id,
            finish_reason=choice.finish_reason,
            usage=usage,
        )


__all__ = [
    "ImageSourceReader",
    "OpenAICompatibleStructuredProvider",
    "RasterArtifactReader",
    "StructuredExtractionProviderError",
]
