import json
import math
from typing import Literal, TypeIs, cast

from grafy_plugin_typesafe.limits import (
    MAX_CHOICE_OPTIONS,
    MAX_OPTION_LABEL_LENGTH,
    MAX_QUESTION_ID_LENGTH,
    MAX_SCORE_LEVELS,
    MAX_TEXT_CHARS,
    MIN_SCORE_LEVELS,
    QUESTION_ID_PATTERN,
)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonContent = str | list[JsonValue] | dict[str, JsonValue]
type QuestionKind = Literal["noul", "choice", "score"]


def require_question_id(value: str) -> str:
    if value != value.strip() or QUESTION_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "Question ids must start with a letter or underscore and contain "
            "only letters, digits, underscores, and hyphens"
        )
    if len(value) > MAX_QUESTION_ID_LENGTH:
        raise ValueError(
            f"Question ids must be at most {MAX_QUESTION_ID_LENGTH} characters"
        )
    return value


def require_bounded_text(value: str, *, what: str) -> str:
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"{what} must be at most {MAX_TEXT_CHARS} characters")
    return value


def canonical_json(value: JsonValue) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def load_json_value(text: str, *, what: str) -> JsonValue:
    _ = require_bounded_text(text, what=what)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{what} must be valid JSON") from exc
    return _require_json_value(parsed, what=what)


def load_json_content(text: str, *, what: str) -> JsonContent:
    value = load_json_value(text, what=what)
    if not _is_json_content(value):
        raise ValueError(f"{what} must be a JSON string, object, or array")
    return value


def load_json_object(text: str, *, what: str) -> dict[str, JsonValue]:
    value = load_json_value(text, what=what)
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object")
    return value


def question_body(
    *,
    kind: QuestionKind,
    instructions: JsonContent,
    criteria: JsonValue | None,
) -> str:
    body: dict[str, JsonValue] = {
        "type": kind,
        "instructions": instructions,
    }
    if criteria is not None:
        body["criteria"] = criteria
    encoded = canonical_json(body)
    _ = require_bounded_text(encoded, what="Question")
    _ = parse_question_body(encoded, expected_kind=kind)
    return encoded


def parse_question_body(
    body: str,
    *,
    expected_kind: QuestionKind | None = None,
) -> tuple[QuestionKind, JsonContent, JsonValue | None]:
    parsed = load_json_object(body, what="Question")
    extra = set(parsed) - {"type", "instructions", "criteria"}
    if extra:
        raise ValueError(
            "Question JSON may only contain type, instructions, and criteria"
        )
    kind = parsed.get("type")
    if kind not in ("noul", "choice", "score"):
        raise ValueError("Question type must be noul, choice, or score")
    if expected_kind is not None and kind != expected_kind:
        raise ValueError(f"Question type must be {expected_kind}")
    if "instructions" not in parsed:
        raise ValueError("Question instructions are required")
    instructions = parsed["instructions"]
    if not _is_json_content(instructions):
        raise ValueError("Question instructions must be a string, object, or array")
    criteria = parsed.get("criteria")
    if kind == "noul":
        _validate_noul_criteria(criteria)
    elif kind == "choice":
        _validate_choice_criteria(criteria)
    else:
        _validate_score_criteria(criteria)
    return kind, instructions, criteria


def parse_options(entries: list[str]) -> dict[str, JsonValue]:
    """Reads ``label`` or ``label: description`` entries into choice criteria."""
    criteria: dict[str, JsonValue] = {}
    for entry in entries:
        label, separator, description = entry.partition(":")
        label = label.strip()
        if label in criteria:
            raise ValueError(f"Choice option {label!r} appears twice")
        description = description.strip()
        criteria[label] = description if separator and description else None
    _validate_choice_criteria(criteria)
    return criteria


def state_content(text: str, *, form: Literal["text", "json"]) -> JsonContent:
    _ = require_bounded_text(text, what="State")
    if form == "text":
        if text.strip() == "":
            raise ValueError("State must not be blank")
        return text
    value = load_json_value(text, what="JSON state")
    if not isinstance(value, dict | list):
        raise ValueError("JSON state must be a JSON object or array")
    if isinstance(value, list) and not value:
        raise ValueError("JSON state array must not be empty")
    return value


def require_instructions(text: str, *, form: Literal["text", "json"]) -> JsonContent:
    _ = require_bounded_text(text, what="Instructions")
    if form == "text":
        if text.strip() == "":
            raise ValueError("Instructions must not be blank")
        return text
    return load_json_content(text, what="Instructions")


def _validate_noul_criteria(criteria: JsonValue | None) -> None:
    if criteria is None:
        return
    if not isinstance(criteria, dict):
        raise ValueError("Noul criteria must be a JSON object")
    extra = set(criteria) - {"true", "false"}
    if extra:
        raise ValueError("Noul criteria may only describe true and false")
    for label in ("true", "false"):
        if label not in criteria:
            continue
        value = criteria[label]
        if value is not None and not _is_json_content(value):
            raise ValueError(
                f"Noul criteria {label} must be a string, object, array, or null"
            )


def _validate_choice_criteria(criteria: JsonValue | None) -> None:
    if not isinstance(criteria, dict) or not criteria:
        raise ValueError("Choice criteria must be a non-empty JSON object")
    if len(criteria) > MAX_CHOICE_OPTIONS:
        raise ValueError(f"Choice criteria accept at most {MAX_CHOICE_OPTIONS} options")
    for label, description in criteria.items():
        if (
            label != label.strip()
            or label == ""
            or len(label) > MAX_OPTION_LABEL_LENGTH
        ):
            raise ValueError(
                "Choice option labels must be non-empty, at most "
                f"{MAX_OPTION_LABEL_LENGTH} characters, and without surrounding "
                "whitespace"
            )
        if description is not None and not _is_json_content(description):
            raise ValueError(
                f"Choice option {label!r} must be a string, object, array, or null"
            )


def _validate_score_criteria(criteria: JsonValue | None) -> None:
    if not isinstance(criteria, list):
        raise ValueError("Score levels must be a JSON array")
    if not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
        raise ValueError(
            f"Score levels must contain {MIN_SCORE_LEVELS} to {MAX_SCORE_LEVELS} "
            "entries"
        )
    for index, level in enumerate(criteria):
        if not _is_json_content(level):
            raise ValueError(f"Score level {index} must be a string, object, or array")


def _require_json_value(value: object, *, what: str) -> JsonValue:
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{what} must not contain NaN or infinite numbers")
        return value
    if isinstance(value, list):
        return [
            _require_json_value(item, what=what) for item in cast(list[object], value)
        ]
    if isinstance(value, dict):
        parsed: dict[str, JsonValue] = {}
        for key, item in cast(dict[object, object], value).items():
            if not isinstance(key, str):
                raise ValueError(f"{what} object keys must be strings")
            parsed[key] = _require_json_value(item, what=what)
        return parsed
    raise ValueError(f"{what} must contain only JSON values")


def _is_json_content(value: JsonValue) -> TypeIs[JsonContent]:
    return isinstance(value, str | dict | list)
