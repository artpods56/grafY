import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from grafy_plugin_typesafe.parsing import parse_question_body, require_question_id


def _finite_unit(value: float, *, what: str) -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{what} must be between 0 and 1")
    return value


def _finite(value: float, *, what: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
    return value


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionPayload(_Payload):
    """One named System One question, stored as the API question object."""

    question_id: StrictStr
    kind: Literal["noul", "choice", "score"]
    body: StrictStr

    @model_validator(mode="after")
    def validate_question(self) -> Self:
        _ = require_question_id(self.question_id)
        _ = parse_question_body(self.body, expected_kind=self.kind)
        return self


class UsagePayload(_Payload):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class NoulAnswerPayload(_Payload):
    question_id: StrictStr
    noul: float

    @model_validator(mode="after")
    def validate_noul(self) -> Self:
        _ = require_question_id(self.question_id)
        _ = _finite_unit(self.noul, what="Noul")
        return self


class ChoiceAnswerPayload(_Payload):
    question_id: StrictStr
    choice: StrictStr = Field(min_length=1)
    confidence: float
    probabilities: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_choice(self) -> Self:
        _ = require_question_id(self.question_id)
        _ = _finite_unit(self.confidence, what="Choice confidence")
        for label, probability in self.probabilities.items():
            if label == "":
                raise ValueError("Choice probability labels must not be empty")
            _ = _finite_unit(probability, what=f"Probability for {label!r}")
        if self.choice not in self.probabilities:
            raise ValueError("Selected choice must be one of the probabilities")
        return self


class ScoreAnswerPayload(_Payload):
    question_id: StrictStr
    score: float
    confidence: float
    levels: list[StrictStr] = Field(min_length=2, max_length=10)
    probabilities: dict[str, float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_score(self) -> Self:
        _ = require_question_id(self.question_id)
        _ = _finite(self.score, what="Score")
        if not 0 <= self.score <= len(self.levels) - 1:
            raise ValueError("Score must fall within the declared levels")
        if set(self.probabilities) != {str(index) for index in range(len(self.levels))}:
            raise ValueError(
                "Score probabilities must cover every declared level index"
            )
        _ = _finite_unit(self.confidence, what="Score confidence")
        for key, probability in self.probabilities.items():
            if not key.isdigit():
                raise ValueError("Score probability keys must be level indexes")
            _ = _finite_unit(probability, what=f"Probability for level {key}")
        return self


class EvaluationPayload(_Payload):
    """One System One response. Answers stay grouped by question type."""

    requested_model: StrictStr = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    base_url: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    usage: UsagePayload
    nouls: list[NoulAnswerPayload] = Field(default_factory=list)
    choices: list[ChoiceAnswerPayload] = Field(default_factory=list)
    scores: list[ScoreAnswerPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_answer_ids(self) -> Self:
        identifiers = [
            answer.question_id for answer in (*self.nouls, *self.choices, *self.scores)
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Evaluation answer ids must be unique")
        return self


class DecisionPayload(_Payload):
    """Whether workflow code should act on an outcome or send it to review."""

    disposition: Literal["act", "review"]
    outcome: StrictStr = Field(min_length=1)
    reason: StrictStr = Field(min_length=1)
    question_id: StrictStr | None = None
    signal: float | None = None

    @model_validator(mode="after")
    def validate_signal(self) -> Self:
        if self.signal is not None:
            _ = _finite_unit(self.signal, what="Decision signal")
        if self.question_id is not None:
            _ = require_question_id(self.question_id)
        return self


class ScoreComponent(_Payload):
    question_id: StrictStr
    score: float
    level_span: int = Field(ge=1)
    normalized: float
    weight: float = Field(gt=0)
    share: float

    @model_validator(mode="after")
    def validate_component(self) -> Self:
        _ = require_question_id(self.question_id)
        _ = _finite(self.score, what="Component score")
        _ = _finite(self.normalized, what="Normalized score")
        _ = _finite_unit(self.share, what="Weight share")
        return self


class CompositeScorePayload(_Payload):
    """Weighted average of normalized score answers. Weights are renormalized."""

    value: float
    components: list[ScoreComponent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_value(self) -> Self:
        _ = _finite(self.value, what="Composite score")
        return self
