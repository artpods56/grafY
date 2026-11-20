import asyncio
import base64
from typing import Final, final, override
from uuid import UUID

import httpx2 as httpx
from mistralai.client import UNSET, Mistral
from mistralai.client import errors as mistral_errors
from mistralai.client.models.documenturlchunk import DocumentURLChunkTypedDict
from mistralai.client.models.imageurlchunk import ImageURLChunkTypedDict
from mistralai.client.models.ocrresponse import OCRResponse
from pydantic import SecretStr

from grafy_core.documents import PdfFile, RasterImage
from grafy_core.egress import EgressPolicy, EgressRejectedError

from grafy_plugin_mistral.egress_transport import EgressPinnedHttpx2Transport
from grafy_core.ocr_contracts import OcrResult

from grafy_plugin_mistral.ocr import (
    MistralOcrConfig,
    build_ocr_output,
    MistralOcrProvider,
    MistralOcrProviderError,
    validate_public_http_url,
)


MISTRAL_API_BASE_URL: Final = "https://api.mistral.ai"
MISTRAL_OCR_MODEL: Final = "mistral-ocr-latest"
MISTRAL_OCR_MAX_SOURCE_BYTES: Final = 50_000_000
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
        egress_policy: EgressPolicy | None = None,
    ) -> None:
        # The Mistral SDK builds its own requests, so the provider endpoint can
        # only be pinned from below. `None` takes the deployment policy named by
        # `GRAFY_EGRESS_TRUSTED_DESTINATIONS`, read when the request is dialed.
        self._egress_policy = egress_policy

    @override
    async def process(
        self,
        *,
        document_url: str | None,
        image: RasterImage | PdfFile | None,
        config: MistralOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> OcrResult:
        if (document_url is None) == (image is None):
            raise MistralOcrProviderError(
                "Connect either a document link or a page image, not both, and "
                "not neither."
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
            document = url_document
        elif image is not None:
            data_url = await self._image_data_url(image)
            if isinstance(image, PdfFile):
                document = {"type": "document_url", "document_url": data_url}
            else:
                document = {"type": "image_url", "image_url": data_url}
        else:
            raise MistralOcrProviderError(
                "Connect either a document link or a page image, not both, and "
                "not neither."
            )

        endpoint = f"{MISTRAL_API_BASE_URL}/v1/ocr"
        api_key_value = api_key.get_secret_value()
        attempts = config.max_retries + 1

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=config.timeout_ms / 1_000,
                transport=EgressPinnedHttpx2Transport(policy=self._egress_policy),
            ) as http_client:
                async with Mistral(
                    api_key=api_key_value,
                    server_url=MISTRAL_API_BASE_URL,
                    async_client=http_client,
                    timeout_ms=config.timeout_ms,
                ) as client:
                    response: OCRResponse | None = None
                    for attempt in range(attempts):
                        try:
                            response = await client.ocr.process_async(
                                model=MISTRAL_OCR_MODEL,
                                document=document,
                                include_image_base64=False,
                                table_format=(
                                    config.table_format
                                    if config.table_format is not None
                                    else UNSET
                                ),
                                extract_header=config.extract_header,
                                extract_footer=config.extract_footer,
                                include_blocks=True,
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
            raise _provider_error(
                exc, endpoint=endpoint, model=MISTRAL_OCR_MODEL
            ) from None

        if response is None:
            raise MistralOcrProviderError(
                f"OCR request to {endpoint!r} produced no response for model "
                f"{MISTRAL_OCR_MODEL!r}"
            )
        return build_ocr_output(response, config)

    async def _image_data_url(self, image: RasterImage | PdfFile) -> str:
        label = image.filename or "this file"
        if isinstance(image, PdfFile):
            content_type = PdfFile.media_type
        elif image.content_type in _SUPPORTED_IMAGE_CONTENT_TYPES:
            content_type = image.content_type
        else:
            raise MistralOcrProviderError(
                f"{label} has unsupported content type {image.content_type!r}"
            )
        try:
            image_bytes = await image.read(max_bytes=MISTRAL_OCR_MAX_SOURCE_BYTES)
        except ValueError as exc:
            if "over the limit" in str(exc):
                raise MistralOcrProviderError(
                    f"{label} exceeds the {MISTRAL_OCR_MAX_SOURCE_BYTES}-byte limit"
                ) from exc
            raise MistralOcrProviderError(f"Failed to read {label}") from exc
        except Exception as exc:
            raise MistralOcrProviderError(f"Failed to read {label}") from exc
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type};base64,{encoded}"


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
    if isinstance(exc, EgressRejectedError):
        return MistralOcrProviderError(
            f"OCR request to {endpoint!r} may not be dialed by this deployment "
            f"for model {model!r}: {exc}"
        )
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
        return "The provider rejected the request. Check the source document."
    if status_code == 401:
        return "The provider did not accept the configured API key."
    if status_code == 402:
        return "The provider requires additional credits or quota for this request."
    if status_code == 403:
        return "The configured API key does not have access to this model or endpoint."
    if status_code == 404:
        return "The Mistral OCR endpoint or latest model is unavailable."
    if status_code == 408:
        return "The provider timed out while processing the request."
    if status_code == 429:
        return "The provider rate limit or account quota was exceeded."
    if 500 <= status_code <= 599:
        return "The provider is currently unavailable or failed while processing."
    return "The provider rejected the request."


__all__ = [
    "MISTRAL_OCR_MAX_SOURCE_BYTES",
    "MistralOcrSdkProvider",
]
