"""OpenAI-compatible vision SDK adapter for contact-sheet crop OCR."""

import asyncio
import base64
import json
import re
from collections.abc import Sequence
from typing import Final, cast, final, override
from uuid import UUID

import httpx
from grafy_core.contracts.ocr import TextReading
from grafy_core.egress import (
    EgressPolicy,
    EgressRejectedError,
    PinnedPublicAddressTransport,
)
from grafy_core.nodes import active_node_context, emit_node_preview, emit_node_progress
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAIError,
)
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from pydantic import BaseModel, ConfigDict, SecretStr, StrictInt, StrictStr, ValidationError

from grafy_plugin_llm.completion_response import (
    check_choice_error,
    parse_chat_completion,
)
from grafy_plugin_llm.crop_reader import (
    VisionLlmCropReaderConfig,
    VisionLlmCropReaderError,
    VisionLlmCropReaderProvider,
)
from grafy_plugin_llm.crop_sheet import CropSheetError, PackedCropSheet, pack_crop_sheets
from grafy_plugin_llm.openai_compatible_sdk import egress_rejection, safe_default_headers

OUTPUT_CONTRACT_INSTRUCTIONS: Final = (
    "You will receive a contact-sheet image containing numbered text crops. "
    "Each crop sits inside a bordered box with a dark numbered badge (1, 2, ..., K) "
    "to its left.\n"
    "Respond ONLY with a valid JSON object matching this exact structure:\n"
    '{"readings": [{"id": 1, "text": "..."}, ...]}\n'
    "Rules:\n"
    "- Return every integer id from 1 to K exactly once, in ascending order.\n"
    '- Use an empty string "" if a crop is blank or completely illegible.\n'
    "- Do not include markdown fences, extra text, or commentary."
)

_FENCE_PATTERN: Final = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)


class _SheetReadingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: StrictInt
    text: StrictStr


class _SheetReadingsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    readings: list[_SheetReadingItem]


class _SheetParseError(ValueError):
    """Recoverable sheet-level response mismatch that triggers bisection."""


def _data_url(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def compose_system_prompt(system_prompt: str) -> str:
    trimmed = system_prompt.strip()
    if trimmed:
        return f"{trimmed}\n\n{OUTPUT_CONTRACT_INSTRUCTIONS}"
    return OUTPUT_CONTRACT_INSTRUCTIONS


def compose_user_prompt(user_prompt: str, crop_count: int) -> str:
    count_instruction = (
        "There is 1 numbered crop (ID 1). Return JSON with its reading."
        if crop_count == 1
        else (
            f"There are {crop_count} numbered crops (IDs 1 through {crop_count}). "
            f"Return JSON with all {crop_count} readings."
        )
    )
    trimmed = user_prompt.strip()
    return f"{trimmed}\n\n{count_instruction}" if trimmed else count_instruction


def _build_messages(
    config: VisionLlmCropReaderConfig,
    *,
    png_bytes: bytes,
    crop_count: int,
) -> list[ChatCompletionMessageParam]:
    parts: list[ChatCompletionContentPartParam] = [
        ChatCompletionContentPartTextParam(
            type="text",
            text=compose_user_prompt(config.user_prompt, crop_count),
        ),
        ChatCompletionContentPartImageParam(
            type="image_url",
            image_url={"url": _data_url(png_bytes)},
        ),
    ]
    return [
        ChatCompletionSystemMessageParam(
            role="system",
            content=compose_system_prompt(config.system_prompt),
        ),
        ChatCompletionUserMessageParam(role="user", content=parts),
    ]


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


def _extract_json_text(content: str) -> str:
    matched = _FENCE_PATTERN.match(content)
    if matched is not None:
        return matched.group(1)
    return content.strip()


def _readings_from_response(
    parsed: _SheetReadingsResponse,
    *,
    expected_count: int,
    model_name: str,
) -> list[TextReading]:
    by_id: dict[int, str] = {}
    for item in parsed.readings:
        if item.id < 1 or item.id > expected_count:
            raise _SheetParseError(
                f"returned out-of-range crop ID {item.id} for {expected_count} crops"
            )
        if item.id in by_id:
            raise _SheetParseError(f"returned duplicate crop ID {item.id}")
        by_id[item.id] = item.text

    if len(by_id) != expected_count:
        raise _SheetParseError(
            f"returned {len(by_id)} readings for {expected_count} crops"
        )

    return [
        TextReading(text=by_id[index], confidence=None, model=model_name)
        for index in range(1, expected_count + 1)
    ]


def _parse_sheet_readings(
    content: str,
    *,
    expected_count: int,
    model_name: str,
) -> list[TextReading]:
    cleaned = _extract_json_text(content)
    try:
        payload: object = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise _SheetParseError("returned invalid JSON") from exc

    try:
        parsed = _SheetReadingsResponse.model_validate(payload)
    except ValidationError as exc:
        raise _SheetParseError("did not match the readings JSON schema") from exc

    return _readings_from_response(
        parsed,
        expected_count=expected_count,
        model_name=model_name,
    )


class _StructuredOutputMode:
    """Tracks whether this endpoint accepts strict JSON Schema response_format."""

    def __init__(self) -> None:
        self.use_json_schema = True


@final
class VisionLlmCropReaderSdkProvider(VisionLlmCropReaderProvider):
    """OpenAI SDK adapter that reads contact-sheet text crops with bisect fallback."""

    def __init__(self, *, egress_policy: EgressPolicy | None = None) -> None:
        # The OpenAI SDK builds its own requests, so the base URL an author named
        # can only be pinned from below. None takes the deployment policy named
        # by GRAFY_EGRESS_TRUSTED_DESTINATIONS, read when the request is dialed.
        self._egress_policy = egress_policy

    @override
    async def recognize(
        self,
        *,
        crops: Sequence[bytes],
        config: VisionLlmCropReaderConfig,
        api_key: SecretStr,
        workspace_id: UUID,
    ) -> list[TextReading]:
        del workspace_id
        if not crops:
            return []

        try:
            sheets = pack_crop_sheets(
                crops,
                max_crops=config.max_sheet_crops,
                max_edge=config.max_sheet_edge,
            )
        except CropSheetError as exc:
            raise VisionLlmCropReaderError(str(exc)) from None

        total = len(crops)
        results: list[TextReading | None] = [None] * total
        completed = 0
        semaphore = asyncio.Semaphore(config.max_concurrency)
        structured_mode = _StructuredOutputMode()
        context = active_node_context()
        endpoint = f"{config.base_url}/chat/completions"
        api_key_value = api_key.get_secret_value()

        await emit_node_progress(
            context,
            "Calling Vision LLM text recognizer…",
            current=0,
            total=total,
        )

        async def run_sheet(sheet_index: int, sheet: PackedCropSheet) -> None:
            nonlocal completed
            sheet_crops = [crops[index] for index in sheet.indices]
            await emit_node_preview(
                context,
                f"Sheet {sheet_index + 1}/{len(sheets)} ({len(sheet_crops)} crops)",
                data=sheet.png_bytes,
                detail=f"{sheet.width}×{sheet.height} px · {config.model}",
            )
            readings = await self._recognize_with_bisect(
                client=client,
                sheet=sheet,
                sheet_crops=sheet_crops,
                config=config,
                endpoint=endpoint,
                semaphore=semaphore,
                structured_mode=structured_mode,
                context=context,
            )
            for crop_index, reading in zip(sheet.indices, readings, strict=True):
                results[crop_index] = reading
            completed += len(readings)
            await emit_node_progress(
                context,
                "Calling Vision LLM text recognizer…",
                current=completed,
                total=total,
            )

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
                try:
                    async with asyncio.TaskGroup() as group:
                        for sheet_index, sheet in enumerate(sheets):
                            group.create_task(run_sheet(sheet_index, sheet))
                except* VisionLlmCropReaderError as exc_group:
                    raise exc_group.exceptions[0] from None

        resolved: list[TextReading] = []
        for reading in results:
            if reading is None:
                raise VisionLlmCropReaderError(
                    "Vision LLM text recognizer did not produce a reading for every crop"
                )
            resolved.append(reading)
        return resolved

    async def _recognize_with_bisect(
        self,
        *,
        client: AsyncOpenAI,
        sheet: PackedCropSheet,
        sheet_crops: Sequence[bytes],
        config: VisionLlmCropReaderConfig,
        endpoint: str,
        semaphore: asyncio.Semaphore,
        structured_mode: _StructuredOutputMode,
        context: object | None = None,
    ) -> list[TextReading]:
        try:
            return await self._call_sheet(
                client=client,
                png_bytes=sheet.png_bytes,
                expected_count=len(sheet_crops),
                config=config,
                endpoint=endpoint,
                semaphore=semaphore,
                structured_mode=structured_mode,
            )
        except _SheetParseError as exc:
            if len(sheet_crops) <= 1:
                raise VisionLlmCropReaderError(
                    f"Vision LLM text recognizer response from {endpoint!r} "
                    f"{exc} for model {config.model!r}"
                ) from None

            midpoint = len(sheet_crops) // 2
            halves = (sheet_crops[:midpoint], sheet_crops[midpoint:])
            readings: list[TextReading] = []
            for half in halves:
                sub_sheets = pack_crop_sheets(
                    half,
                    max_crops=len(half),
                    max_edge=config.max_sheet_edge,
                )
                for sub_sheet in sub_sheets:
                    sub_crops = [half[index] for index in sub_sheet.indices]
                    await emit_node_preview(
                        context,
                        f"Bisect retry ({len(sub_crops)} {'crop' if len(sub_crops) == 1 else 'crops'})",
                        data=sub_sheet.png_bytes,
                        detail=f"{sub_sheet.width}×{sub_sheet.height} px · {config.model}",
                    )
                    readings.extend(
                        await self._recognize_with_bisect(
                            client=client,
                            sheet=sub_sheet,
                            sheet_crops=sub_crops,
                            config=config,
                            endpoint=endpoint,
                            semaphore=semaphore,
                            structured_mode=structured_mode,
                            context=context,
                        )
                    )
            return readings

    async def _call_sheet(
        self,
        *,
        client: AsyncOpenAI,
        png_bytes: bytes,
        expected_count: int,
        config: VisionLlmCropReaderConfig,
        endpoint: str,
        semaphore: asyncio.Semaphore,
        structured_mode: _StructuredOutputMode,
    ) -> list[TextReading]:
        messages = _build_messages(
            config,
            png_bytes=png_bytes,
            crop_count=expected_count,
        )

        async def send(*, with_schema: bool):
            if with_schema:
                return await client.chat.completions.with_raw_response.parse(
                    model=config.model,
                    messages=messages,
                    temperature=config.temperature,
                    max_completion_tokens=config.max_completion_tokens,
                    response_format=_SheetReadingsResponse,
                )
            return await client.chat.completions.with_raw_response.create(
                model=config.model,
                messages=messages,
                temperature=config.temperature,
                max_completion_tokens=config.max_completion_tokens,
            )

        try:
            async with semaphore:
                use_schema = structured_mode.use_json_schema
                try:
                    raw_response = await send(with_schema=use_schema)
                except APIStatusError as exc:
                    if exc.status_code == 400 and use_schema:
                        raw_response = await send(with_schema=False)
                        structured_mode.use_json_schema = False
                    else:
                        raise
        except APITimeoutError:
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer request to {endpoint!r} timed out "
                f"for model {config.model!r}"
            ) from None
        except APIStatusError as exc:
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer request to {endpoint!r} returned HTTP "
                f"{exc.status_code} for model {config.model!r}. "
                f"{_status_guidance(exc.status_code)}"
            ) from None
        except (APIConnectionError, EgressRejectedError) as exc:
            rejection = egress_rejection(exc)
            if rejection is not None:
                raise VisionLlmCropReaderError(
                    f"Vision LLM text recognizer request to {endpoint!r} may not be "
                    f"dialed by this deployment for model {config.model!r}: {rejection}"
                ) from None
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer request to {endpoint!r} could not connect "
                f"for model {config.model!r}"
            ) from None
        except APIResponseValidationError:
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer response from {endpoint!r} did not match "
                f"the SDK response model for {config.model!r}"
            ) from None
        except OpenAIError as exc:
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer request to {endpoint!r} failed for model "
                f"{config.model!r} with {exc.__class__.__name__}"
            ) from None

        parsed_model: _SheetReadingsResponse | None = None
        raw_payload: object
        try:
            sdk_completion = raw_response.parse()
        except LengthFinishReasonError:
            raise _SheetParseError(
                "was truncated (finish_reason='length') before emitting readings; "
                "try increasing max_completion_tokens"
            ) from None
        except ContentFilterFinishReasonError:
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer response from {endpoint!r} was filtered "
                f"by the content filter for model {config.model!r}"
            ) from None
        except (ValidationError, TypeError):
            # Model returned fenced/non-conforming JSON in parse() mode, or a
            # gateway returned HTTP 200 with {"error": ...} and no choices.
            # Fall back to the raw response text for tolerant inspection.
            raw_text = raw_response.text
            try:
                raw_payload = cast(object, json.loads(raw_text))
            except json.JSONDecodeError:
                raw_payload = raw_text
        else:
            raw_payload = cast(object, sdk_completion)
            if sdk_completion.choices:
                maybe_parsed: object = getattr(
                    sdk_completion.choices[0].message, "parsed", None
                )
                if isinstance(maybe_parsed, _SheetReadingsResponse):
                    parsed_model = maybe_parsed

        parsed = parse_chat_completion(
            raw_payload,
            endpoint=endpoint,
            model=config.model,
            service_name="Vision LLM text recognizer",
            error_type=VisionLlmCropReaderError,
        )

        if not parsed.choices:
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer response from {endpoint!r} contained no "
                f"choices for model {config.model!r}"
            )
        choice = parsed.choices[0]
        check_choice_error(
            choice,
            endpoint=endpoint,
            model=config.model,
            service_name="Vision LLM text recognizer",
            error_type=VisionLlmCropReaderError,
        )
        if choice.message.refusal is not None and choice.message.refusal != "":
            raise VisionLlmCropReaderError(
                f"Vision LLM text recognizer choice {choice.index} was refused for "
                f"model {config.model!r}"
            )

        model_name = (parsed.model or "").strip() or config.model
        if parsed_model is not None:
            return _readings_from_response(
                parsed_model,
                expected_count=expected_count,
                model_name=model_name,
            )

        assistant_content = choice.message.text_content()
        if assistant_content is None or not assistant_content.strip():
            if choice.finish_reason == "length":
                raise _SheetParseError(
                    "was truncated (finish_reason='length') before emitting readings; "
                    "try increasing max_completion_tokens"
                )
            raise _SheetParseError("did not contain text")

        return _parse_sheet_readings(
            assistant_content,
            expected_count=expected_count,
            model_name=model_name,
        )
