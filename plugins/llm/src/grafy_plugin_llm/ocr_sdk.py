import base64
from io import BytesIO
from typing import Final, cast, final, override
from uuid import UUID

import httpx
from grafy_core.artifact_contracts import MarkdownValue
from grafy_core.contracts.ocr import DocumentOcrResult
from grafy_core.documents import PdfFile, RasterImage
from grafy_core.egress import EgressPolicy, EgressRejectedError, PinnedPublicAddressTransport
from grafy_core.nodes import active_node_context, emit_node_progress
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
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
from openai.types.chat.completion_create_params import CompletionCreateParamsNonStreaming
from PIL import Image
from pydantic import SecretStr, ValidationError

from grafy_plugin_llm.ocr import (
    VisionLlmOcrConfig,
    VisionLlmOcrProvider,
    VisionLlmOcrProviderError,
)
from grafy_plugin_llm.openai_compatible_sdk import egress_rejection, safe_default_headers

VISION_LLM_OCR_MAX_IMAGE_BYTES: Final = 20_000_000
_DIRECT_IMAGE_TYPES: Final = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }
)
_PNG_CONVERSION_TYPES: Final = frozenset({"image/bmp", "image/tiff"})
_PDF_MESSAGE: Final = (
    "Vision LLM OCR supports raster images only; PDF documents are not supported yet."
)


def _png_bytes(image_bytes: bytes, label: str) -> bytes:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            bands = image.getbands()
            converted = image.convert("RGBA" if "A" in bands else "RGB")
            buffer = BytesIO()
            converted.save(buffer, format="PNG")
    except Exception as exc:
        raise VisionLlmOcrProviderError(
            f"Could not convert {label} to PNG for Vision LLM OCR."
        ) from exc
    return buffer.getvalue()


def _data_url(mime: str, image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def _image_data_url(image: RasterImage) -> str:
    label = image.filename or "this image"
    try:
        image_bytes = await image.read(max_bytes=VISION_LLM_OCR_MAX_IMAGE_BYTES)
    except ValueError as exc:
        if "over the limit" in str(exc):
            raise VisionLlmOcrProviderError(
                f"{label} exceeds the {VISION_LLM_OCR_MAX_IMAGE_BYTES}-byte limit"
            ) from exc
        raise VisionLlmOcrProviderError(f"Failed to read {label}") from exc
    except Exception as exc:
        raise VisionLlmOcrProviderError(f"Failed to read {label}") from exc

    content_type = image.content_type
    if content_type in _DIRECT_IMAGE_TYPES:
        # image/jpg is not an IANA type. Vision APIs expect image/jpeg.
        mime = "image/jpeg" if content_type == "image/jpg" else content_type
        return _data_url(mime, image_bytes)
    if content_type in _PNG_CONVERSION_TYPES:
        return _data_url("image/png", _png_bytes(image_bytes, label))
    raise VisionLlmOcrProviderError(
        f"{label} has unsupported content type {content_type!r}"
    )


def _messages(config: VisionLlmOcrConfig, data_url: str) -> list[ChatCompletionMessageParam]:
    messages: list[ChatCompletionMessageParam] = []
    if config.system_prompt.strip():
        messages.append(
            ChatCompletionSystemMessageParam(
                role="system",
                content=config.system_prompt,
            )
        )
    parts: list[ChatCompletionContentPartParam] = []
    if config.user_prompt:
        parts.append(
            ChatCompletionContentPartTextParam(type="text", text=config.user_prompt)
        )
    parts.append(
        ChatCompletionContentPartImageParam(
            type="image_url",
            image_url={"url": data_url},
        )
    )
    messages.append(ChatCompletionUserMessageParam(role="user", content=parts))
    return messages


def _status_guidance(status_code: int) -> str:
    if status_code == 400:
        return (
            "The provider rejected the request. Check whether the model "
            "accepts image inputs."
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
        return (
            "The provider is currently unavailable or failed while "
            "processing the request."
        )
    return "The provider rejected the request."


def _completion_text(completion: ChatCompletion, *, endpoint: str, model: str) -> str:
    if not completion.choices:
        raise VisionLlmOcrProviderError(
            f"Vision LLM OCR response from {endpoint!r} contained no choices "
            f"for model {model!r}"
        )
    choice = completion.choices[0]
    if choice.message.refusal is not None and choice.message.refusal != "":
        raise VisionLlmOcrProviderError(
            f"Vision LLM OCR choice {choice.index} was refused for model {model!r}"
        )
    assistant_content = choice.message.content
    if assistant_content is None or assistant_content == "":
        raise VisionLlmOcrProviderError(
            f"Vision LLM OCR choice {choice.index} did not contain text for "
            f"model {model!r}"
        )
    return assistant_content


@final
class VisionLlmOcrSdkProvider(VisionLlmOcrProvider):
    """OpenAI SDK adapter that transcribes one raster image into Markdown."""

    def __init__(self, *, egress_policy: EgressPolicy | None = None) -> None:
        # The OpenAI SDK builds its own requests, so the base URL an author named
        # can only be pinned from below. None takes the deployment policy named
        # by GRAFY_EGRESS_TRUSTED_DESTINATIONS, read when the request is dialed.
        self._egress_policy = egress_policy

    @override
    async def process(
        self,
        *,
        document: RasterImage | PdfFile,
        config: VisionLlmOcrConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> DocumentOcrResult:
        del workspace_id
        if isinstance(document, PdfFile):
            raise VisionLlmOcrProviderError(_PDF_MESSAGE)

        await emit_node_progress(active_node_context(), "Preparing image…")
        data_url = await _image_data_url(document)
        request: CompletionCreateParamsNonStreaming = {
            "model": config.model,
            "messages": _messages(config, data_url),
            "temperature": config.temperature,
            "max_completion_tokens": config.max_completion_tokens,
        }
        endpoint = f"{config.base_url}/chat/completions"
        api_key_value = api_key.get_secret_value()

        try:
            async with httpx.AsyncClient(
                timeout=config.timeout_ms / 1_000,
                limits=httpx.Limits(
                    max_connections=1000, max_keepalive_connections=100
                ),
                follow_redirects=False,
                transport=PinnedPublicAddressTransport(policy=self._egress_policy),
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
                    default_headers=cast(dict[str, str], safe_default_headers(api_key_value)),
                    # The SDK stub types this as httpx2; runtime accepts this httpx client.
                    http_client=http_client,  # pyright: ignore[reportArgumentType]
                ) as client:
                    await emit_node_progress(
                        active_node_context(), "Calling Vision LLM OCR…"
                    )
                    completion = await client.chat.completions.create(**request)
        except APITimeoutError:
            raise VisionLlmOcrProviderError(
                f"Vision LLM OCR request to {endpoint!r} timed out for model "
                f"{config.model!r}"
            ) from None
        except APIStatusError as exc:
            raise VisionLlmOcrProviderError(
                f"Vision LLM OCR request to {endpoint!r} returned HTTP "
                f"{exc.status_code} for model {config.model!r}. "
                f"{_status_guidance(exc.status_code)}"
            ) from None
        except (APIConnectionError, EgressRejectedError) as exc:
            rejection = egress_rejection(exc)
            if rejection is not None:
                raise VisionLlmOcrProviderError(
                    f"Vision LLM OCR request to {endpoint!r} may not be dialed "
                    f"by this deployment for model {config.model!r}: {rejection}"
                ) from None
            raise VisionLlmOcrProviderError(
                f"Vision LLM OCR request to {endpoint!r} could not connect for "
                f"model {config.model!r}"
            ) from None
        except APIResponseValidationError:
            raise VisionLlmOcrProviderError(
                f"Vision LLM OCR response from {endpoint!r} did not match the "
                f"SDK response model for {config.model!r}"
            ) from None
        except OpenAIError as exc:
            raise VisionLlmOcrProviderError(
                f"Vision LLM OCR request to {endpoint!r} failed for model "
                f"{config.model!r} with {exc.__class__.__name__}"
            ) from None

        try:
            completion = ChatCompletion.model_validate(completion.model_dump())
        except ValidationError:
            raise VisionLlmOcrProviderError(
                f"Vision LLM OCR response from {endpoint!r} did not match the "
                f"SDK response model for {config.model!r}"
            ) from None

        markdown = _completion_text(completion, endpoint=endpoint, model=config.model)
        return DocumentOcrResult(
            markdown=MarkdownValue(markdown=markdown),
            blocks=None,
            regions=None,
        )
