import asyncio
import base64
from hashlib import sha256
from typing import Final, final, override
from uuid import UUID

import httpx2 as httpx
from mistralai.client import UNSET, Mistral
from mistralai.client import errors as mistral_errors
from mistralai.client.models.documenturlchunk import DocumentURLChunkTypedDict
from mistralai.client.models.imageurlchunk import ImageURLChunkTypedDict
from mistralai.client.models.ocrresponse import OCRResponse
from mistralai.client.models.responseformat import ResponseFormat
from pydantic import SecretStr

from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_core.artifacts import ArtifactRef
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.schema_contracts import parse_json_schema

from grafy_plugin_mistral.artifacts import OcrDocumentPayload
from grafy_plugin_mistral.ocr import (
    MistralOcrConfig,
    MistralOcrProvider,
    MistralOcrProviderError,
    validate_public_http_url,
)


MISTRAL_OCR_MAX_SOURCE_BYTES: Final = 50_000_000
MISTRAL_OCR_MAX_IMAGE_BASE64_CHARS: Final = 50_000_000
_RETRYABLE_STATUS: Final = frozenset({408, 429, 500, 502, 503, 504})
_SUPPORTED_IMAGE_CONTENT_TYPES: Final = frozenset(
    {
        "image/bmp",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    }
)


@final
class MistralOcrSdkProvider(MistralOcrProvider):
    """Mistral SDK adapter for the OCR process endpoint."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        storage: FileStoragePort,
    ) -> None:
        self._uow = uow
        self._storage = storage

    @override
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
        if (document_url is None) == (image is None):
            raise MistralOcrProviderError(
                "Mistral OCR requires exactly one of a document URL or a raster image"
            )
        if config.document_annotation_prompt is not None and (
            document_annotation_schema is None
        ):
            raise MistralOcrProviderError(
                "Mistral OCR document annotation prompt requires a document "
                "annotation schema"
            )

        document: DocumentURLChunkTypedDict | ImageURLChunkTypedDict
        if document_url is not None:
            try:
                document_url = validate_public_http_url(
                    document_url,
                    label="document_url",
                    allow_query=True,
                    strip_trailing_slash=False,
                )
            except ValueError as exc:
                raise MistralOcrProviderError(str(exc)) from None
            url_document: DocumentURLChunkTypedDict = {
                "type": "document_url",
                "document_url": document_url,
            }
            if config.document_name is not None:
                url_document["document_name"] = config.document_name
            document = url_document
            source_image_id = None
        elif image is not None:
            data_url = await self._image_data_url(image, workspace_id=workspace_id)
            document = {"type": "image_url", "image_url": data_url}
            source_image_id = image.artifact_id
        else:
            raise MistralOcrProviderError(
                "Mistral OCR requires exactly one of a document URL or a raster image"
            )

        document_format = _annotation_format(
            document_annotation_schema,
            name=config.document_annotation_schema_name,
            strict=config.strict,
            label="document annotation",
        )
        bbox_format = _annotation_format(
            bbox_annotation_schema,
            name=config.bbox_annotation_schema_name,
            strict=config.strict,
            label="bounding-box annotation",
        )
        endpoint = f"{config.base_url}/v1/ocr"
        api_key_value = api_key.get_secret_value()
        attempts = config.max_retries + 1

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=config.timeout_ms / 1_000,
            ) as http_client:
                async with Mistral(
                    api_key=api_key_value,
                    server_url=config.base_url,
                    async_client=http_client,
                    timeout_ms=config.timeout_ms,
                ) as client:
                    response: OCRResponse | None = None
                    for attempt in range(attempts):
                        try:
                            response = await client.ocr.process_async(
                                model=config.model,
                                document=document,
                                pages=(
                                    config.pages if config.pages is not None else UNSET
                                ),
                                include_image_base64=config.include_image_base64,
                                image_limit=(
                                    config.image_limit
                                    if config.image_limit is not None
                                    else UNSET
                                ),
                                image_min_size=(
                                    config.image_min_size
                                    if config.image_min_size is not None
                                    else UNSET
                                ),
                                bbox_annotation_format=(
                                    bbox_format if bbox_format is not None else UNSET
                                ),
                                document_annotation_format=(
                                    document_format
                                    if document_format is not None
                                    else UNSET
                                ),
                                document_annotation_prompt=(
                                    config.document_annotation_prompt
                                    if config.document_annotation_prompt is not None
                                    else UNSET
                                ),
                                table_format=(
                                    config.table_format
                                    if config.table_format is not None
                                    else UNSET
                                ),
                                extract_header=config.extract_header,
                                extract_footer=config.extract_footer,
                                include_blocks=config.include_blocks,
                                confidence_scores_granularity=(
                                    config.confidence_scores_granularity
                                    if config.confidence_scores_granularity is not None
                                    else UNSET
                                ),
                                retries=None,
                                timeout_ms=config.timeout_ms,
                            )
                            break
                        except Exception as exc:
                            if attempt + 1 >= attempts or not _retryable(exc):
                                raise
                            await asyncio.sleep(min(2.0, 0.25 * (2**attempt)))
        except MistralOcrProviderError:
            raise
        except Exception as exc:
            raise _provider_error(exc, endpoint=endpoint, model=config.model) from None

        if response is None:
            raise MistralOcrProviderError(
                f"OCR request to {endpoint!r} produced no response for model "
                f"{config.model!r}"
            )
        try:
            payload = OcrDocumentPayload.from_sdk(
                response,
                base_url=config.base_url,
                document_kind="document_url"
                if source_image_id is None
                else "image_url",
                source_image_artifact_id=source_image_id,
                table_format=config.table_format,
                include_image_base64=config.include_image_base64,
                include_blocks=config.include_blocks,
                document_annotation_schema=document_annotation_schema,
                document_annotation_schema_name=config.document_annotation_schema_name,
                bbox_annotation_schema=bbox_annotation_schema,
                bbox_annotation_schema_name=config.bbox_annotation_schema_name,
            )
        except ValueError:
            raise MistralOcrProviderError(
                f"OCR response for model {config.model!r} could not be stored: "
                "the response or annotations did not match the expected schema"
            ) from None
        encoded_chars = sum(
            len(image.image_base64)
            for page in payload.pages
            for image in page.images
            if image.image_base64 is not None
        )
        if encoded_chars > MISTRAL_OCR_MAX_IMAGE_BASE64_CHARS:
            raise MistralOcrProviderError(
                "Extracted image bytes exceed "
                f"{MISTRAL_OCR_MAX_IMAGE_BASE64_CHARS} base64 characters. "
                "Turn off include_image_base64 or lower image_limit."
            )
        return payload

    async def _image_data_url(
        self,
        ref: ArtifactRef,
        *,
        workspace_id: UUID,
    ) -> str:
        if ref.key() != RASTER_IMAGE.key:
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} must reference "
                f"{RASTER_IMAGE.key.id}@{RASTER_IMAGE.key.schema_version}, "
                f"got {ref.artifact_type}@{ref.schema_version}"
            )
        try:
            async with self._uow as uow:
                artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        except Exception as exc:
            raise MistralOcrProviderError(
                f"Failed to look up raster image {ref.artifact_id}"
            ) from exc
        if artifact is None or artifact.workspace_id != workspace_id:
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} was not found"
            )
        if artifact.ref() != ref:
            raise MistralOcrProviderError(
                f"Artifact repository returned a different ref for raster image "
                f"{ref.artifact_id}"
            )
        if artifact.bucket is None or artifact.object_key is None:
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} does not have a storage object"
            )
        if artifact.content_type not in _SUPPORTED_IMAGE_CONTENT_TYPES:
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} has unsupported content type "
                f"{artifact.content_type!r}"
            )
        if (
            artifact.byte_size is not None
            and artifact.byte_size > MISTRAL_OCR_MAX_SOURCE_BYTES
        ):
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} exceeds the "
                f"{MISTRAL_OCR_MAX_SOURCE_BYTES}-byte limit"
            )

        try:
            stream = await self._storage.load(
                bucket=artifact.bucket,
                path=artifact.object_key,
            )
            try:
                image_bytes = stream.read(MISTRAL_OCR_MAX_SOURCE_BYTES + 1)
            finally:
                stream.close()
        except Exception as exc:
            raise MistralOcrProviderError(
                f"Failed to load raster image {ref.artifact_id} from "
                f"{artifact.bucket}/{artifact.object_key}"
            ) from exc

        if len(image_bytes) > MISTRAL_OCR_MAX_SOURCE_BYTES:
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} exceeds the "
                f"{MISTRAL_OCR_MAX_SOURCE_BYTES}-byte limit"
            )
        if artifact.byte_size is not None and len(image_bytes) != artifact.byte_size:
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} size does not match its metadata"
            )
        actual_sha256 = sha256(image_bytes).hexdigest()
        expected_hashes = {
            expected
            for expected in (artifact.sha256, ref.content_hash)
            if expected is not None
        }
        if any(expected != actual_sha256 for expected in expected_hashes):
            raise MistralOcrProviderError(
                f"Raster image {ref.artifact_id} SHA-256 does not match"
            )

        content_type = artifact.content_type
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type};base64,{encoded}"


def _annotation_format(
    schema: str | None,
    *,
    name: str,
    strict: bool,
    label: str,
) -> ResponseFormat | None:
    if schema is None:
        return None
    try:
        definition = parse_json_schema(schema, context=f"{label} schema {name!r}")
    except ValueError as exc:
        raise MistralOcrProviderError(str(exc)) from None
    return ResponseFormat.model_validate(
        {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "schema": definition,
                "strict": strict,
            },
        }
    )


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and status_code in _RETRYABLE_STATUS


def _provider_error(
    exc: Exception,
    *,
    endpoint: str,
    model: str,
) -> MistralOcrProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return MistralOcrProviderError(
            f"OCR request to {endpoint!r} timed out for model {model!r}"
        )
    if isinstance(exc, httpx.NetworkError):
        return MistralOcrProviderError(
            f"OCR request to {endpoint!r} could not connect for model {model!r}"
        )
    if isinstance(exc, mistral_errors.ResponseValidationError):
        return MistralOcrProviderError(
            f"OCR response from {endpoint!r} did not match the SDK response "
            f"model for {model!r}"
        )
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return MistralOcrProviderError(
            f"OCR request to {endpoint!r} returned HTTP {status_code} for model "
            f"{model!r}. {_status_guidance(status_code)}"
        )
    return MistralOcrProviderError(
        f"OCR request to {endpoint!r} failed for model {model!r} with "
        f"{exc.__class__.__name__}"
    )


def _status_guidance(status_code: int) -> str:
    if status_code == 400 or status_code == 422:
        return (
            "The provider rejected the request. Check the model, document, "
            "page selection, and annotation schemas."
        )
    if status_code == 401:
        return "The provider did not accept the configured API key."
    if status_code == 402:
        return "The provider requires additional credits or quota for this request."
    if status_code == 403:
        return "The configured API key does not have access to this model or endpoint."
    if status_code == 404:
        return "Check that the base URL and model identifier are correct."
    if status_code == 408:
        return "The provider timed out while processing the request."
    if status_code == 429:
        return "The provider rate limit or account quota was exceeded."
    if 500 <= status_code <= 599:
        return "The provider is currently unavailable or failed while processing."
    return "The provider rejected the request."


__all__ = [
    "MISTRAL_OCR_MAX_IMAGE_BASE64_CHARS",
    "MISTRAL_OCR_MAX_SOURCE_BYTES",
    "MistralOcrSdkProvider",
]
