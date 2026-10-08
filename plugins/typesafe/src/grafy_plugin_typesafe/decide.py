from typing import Annotated, Literal, Self

from pydantic import Field, StrictStr, model_validator

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import InPort, OutPort
from grafy_core.plugins import NodeCachePolicy

from grafy_plugin_typesafe.artifacts import DECISION, EVALUATION
from grafy_plugin_typesafe.connection import QuestionId, raise_shown
from grafy_plugin_typesafe.declaration import TYPESAFE
from grafy_plugin_typesafe.limits import MAX_QUESTIONS
from grafy_plugin_typesafe.lookup import answer_kind, find_choice, find_noul
from grafy_plugin_typesafe.models import DecisionPayload, EvaluationPayload


class DecideConfig(NodeConfig):
    question_ids: list[QuestionId] = Field(
        min_length=1,
        max_length=MAX_QUESTIONS,
        description="Noul ids to decide together, or one choice id.",
    )
    require: Literal["any", "all"] = Field(
        default="any",
        description=(
            "Nouls only. any: yes when at least one noul is yes, as in a guard. "
            "all: yes only when every noul is yes."
        ),
    )
    yes_at: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Nouls only. Yes at or above this probability.",
    )
    no_at: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Nouls only. No at or below this probability. Between the two, review.",
    )
    minimum_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Choice only. Review the choice when its confidence is lower.",
    )
    allow: list[StrictStr] = Field(
        default_factory=list,
        description="Choice only. When set, any other choice goes to review.",
    )

    @model_validator(mode="after")
    def valid_rule(self) -> Self:
        if self.no_at >= self.yes_at:
            raise ValueError("no_at must be less than yes_at")
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError("Decide question ids must be unique")
        return self


class DecideInput(NodeInput):
    evaluation: Annotated[
        EvaluationPayload,
        InPort(EVALUATION),
        Field(description="Evaluation that holds the answers to decide on."),
    ]


class DecideOutput(NodeOutput):
    decision: Annotated[
        DecisionPayload,
        OutPort(DECISION),
        Field(description="Act on the outcome, or send it to review."),
    ]


def decide(evaluation: EvaluationPayload, config: DecideConfig) -> DecisionPayload:
    kinds: list[str] = []
    for question_id in config.question_ids:
        kind = answer_kind(question_id, evaluation)
        if kind is None:
            raise ValueError(f"Evaluation has no answer named {question_id!r}")
        kinds.append(kind)
    if "score" in kinds:
        raise ValueError(
            "Decide reads nouls and choices. Use Combine scores for score answers."
        )
    if set(kinds) == {"noul"}:
        if config.allow:
            raise ValueError("allow applies only to a choice")
        return _decide_nouls(evaluation, config)
    if set(kinds) != {"choice"}:
        raise ValueError("Decide reads either nouls or one choice, not both")
    if len(kinds) > 1:
        raise ValueError("Decide reads one choice at a time")
    return _decide_choice(evaluation, config)


def _decide_nouls(
    evaluation: EvaluationPayload, config: DecideConfig
) -> DecisionPayload:
    answers = [
        find_noul(evaluation, question_id) for question_id in config.question_ids
    ]
    if config.require == "any":
        deciding = max(answers, key=lambda answer: answer.noul)
    else:
        deciding = min(answers, key=lambda answer: answer.noul)
    if len(answers) == 1:
        subject = f"Noul {deciding.question_id!r}"
    elif config.require == "any":
        subject = f"Highest noul {deciding.question_id!r}"
    else:
        subject = f"Lowest noul {deciding.question_id!r}"

    value = deciding.noul
    if value >= config.yes_at:
        outcome = "yes"
        reason = f"{subject} is {value:.3f}, at least {config.yes_at:.3f}"
    elif value <= config.no_at:
        outcome = "no"
        reason = f"{subject} is {value:.3f}, at most {config.no_at:.3f}"
    else:
        outcome = "review"
        reason = (
            f"{subject} is {value:.3f}, between {config.no_at:.3f} and "
            f"{config.yes_at:.3f}"
        )
    return DecisionPayload(
        disposition="review" if outcome == "review" else "act",
        outcome=outcome,
        reason=reason,
        question_id=deciding.question_id,
        signal=value,
    )


def _decide_choice(
    evaluation: EvaluationPayload, config: DecideConfig
) -> DecisionPayload:
    answer = find_choice(evaluation, config.question_ids[0])
    if answer.confidence < config.minimum_confidence:
        disposition = "review"
        reason = (
            f"Confidence {answer.confidence:.3f} is below "
            f"{config.minimum_confidence:.3f}"
        )
    elif config.allow and answer.choice not in config.allow:
        disposition = "review"
        reason = f"Choice {answer.choice!r} is not in the allow list"
    else:
        disposition = "act"
        reason = f"Choice {answer.choice!r} has confidence {answer.confidence:.3f}"
    return DecisionPayload(
        disposition=disposition,
        outcome=answer.choice,
        reason=reason,
        question_id=answer.question_id,
        signal=answer.confidence,
    )


@TYPESAFE.function_node(
    operator_id="typesafe.decide",
    version=1,
    title="Decide",
    cache_policy=NodeCachePolicy.EXACT,
)
async def decide_node(config: DecideConfig, inputs: DecideInput) -> DecideOutput:
    """Turns nouls into yes, no, or review, or accepts a choice. Runs locally."""

    try:
        return DecideOutput(decision=decide(inputs.evaluation, config))
    except ValueError as exc:
        raise_shown(exc)
