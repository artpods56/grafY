"""Tolerant parsing of OpenAI-compatible Chat Completions responses.

OpenAI-compatible gateways such as OpenRouter, vLLM, and LiteLLM return extra
fields (``provider``, ``reasoning``, ``reasoning_details``, ``cost``), non-OpenAI
``service_tier`` values, ``finish_reason: null`` or ``"error"``, multi-part
message content lists, and occasionally HTTP 200 responses carrying a top-level
or choice-level ``error`` object. Validating the strict OpenAI SDK
``ChatCompletion`` model rejects those responses even when the completion itself
is valid or hides the actual upstream error code behind a schema failure.

This module validates only the fields GrafY actually reads and never echoes raw
provider response bodies into user-facing exceptions or logs.
"""

import logging
from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


class CompatCompletionUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class CompatCompletionMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str | None = None
    content: str | list[dict[str, object]] | None = None
    refusal: str | None = None

    def text_content(self) -> str | None:
        if self.content is None:
            return None
        if isinstance(self.content, str):
            return self.content
        parts: list[str] = []
        for item in self.content:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts) if parts else None


class CompatCompletionChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    finish_reason: str | None = None
    message: CompatCompletionMessage
    error: dict[str, object] | None = None


class CompatChatCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    model: str | None = None
    choices: list[CompatCompletionChoice]
    usage: CompatCompletionUsage | None = None


def http_status_guidance(status_code: int) -> str:
    if status_code == 400:
        return (
            "The provider rejected the request. Check whether the model "
            "accepts the supplied inputs and response format."
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


def _safe_error_code(error_obj: object) -> int | None:
    if not isinstance(error_obj, Mapping):
        return None
    mapping = cast(Mapping[str, object], error_obj)
    raw_code = mapping.get("code")
    if isinstance(raw_code, int) and not isinstance(raw_code, bool):
        return raw_code
    return None


def _raise_embedded_error[ErrorT: Exception](
    error_obj: object,
    *,
    endpoint: str,
    model: str,
    service_name: str,
    error_type: type[ErrorT],
) -> None:
    code = _safe_error_code(error_obj)
    logger.warning(
        "llm_completion_embedded_error endpoint=%s model=%s code=%s",
        endpoint,
        model,
        code,
    )
    if code is not None:
        raise error_type(
            f"{service_name} request to {endpoint!r} returned HTTP {code} "
            f"for model {model!r}. {http_status_guidance(code)}"
        ) from None
    raise error_type(
        f"{service_name} request to {endpoint!r} returned a provider error "
        f"for model {model!r}."
    ) from None


def parse_chat_completion[ErrorT: Exception](
    raw: object,
    *,
    endpoint: str,
    model: str,
    service_name: str,
    error_type: type[ErrorT],
) -> CompatChatCompletion:
    """Validate an OpenAI SDK completion object without breaking on compatible gateways."""

    payload: dict[str, object] | None = None
    if isinstance(raw, BaseModel):
        payload = cast(dict[str, object], raw.model_dump(warnings=False))
    elif isinstance(raw, Mapping):
        mapping = cast(Mapping[object, object], raw)
        payload = {str(k): v for k, v in mapping.items()}

    if payload is None:
        raw_type_name = type(cast(object, raw)).__name__
        logger.warning(
            "llm_completion_non_mapping endpoint=%s model=%s type=%s",
            endpoint,
            model,
            raw_type_name,
        )
        raise error_type(
            f"{service_name} response from {endpoint!r} did not match the "
            f"SDK response model for {model!r}"
        ) from None

    # OpenRouter and some gateways return HTTP 200 with a top-level ``error``
    # object and no choices when an upstream provider fails mid-request.
    embedded_error = payload.get("error")
    choices_raw = payload.get("choices")
    if embedded_error is not None and not choices_raw:
        _raise_embedded_error(
            embedded_error,
            endpoint=endpoint,
            model=model,
            service_name=service_name,
            error_type=error_type,
        )

    try:
        parsed = CompatChatCompletion.model_validate(payload)
    except ValidationError as exc:
        locs = [
            (".".join(str(part) for part in err["loc"]), err["type"])
            for err in exc.errors()
        ]
        logger.warning(
            "llm_completion_validation_failed endpoint=%s model=%s errors=%s",
            endpoint,
            model,
            locs,
        )
        raise error_type(
            f"{service_name} response from {endpoint!r} did not match the "
            f"SDK response model for {model!r}"
        ) from None

    return parsed


def check_choice_error[ErrorT: Exception](
    choice: CompatCompletionChoice,
    *,
    endpoint: str,
    model: str,
    service_name: str,
    error_type: type[ErrorT],
) -> None:
    """Raise a safe provider error when a choice itself carries an OpenRouter error."""

    if choice.error is not None or choice.finish_reason == "error":
        _raise_embedded_error(
            choice.error,
            endpoint=endpoint,
            model=model,
            service_name=service_name,
            error_type=error_type,
        )


__all__ = [
    "CompatChatCompletion",
    "CompatCompletionChoice",
    "CompatCompletionMessage",
    "CompatCompletionUsage",
    "check_choice_error",
    "http_status_guidance",
    "parse_chat_completion",
]
