from typing import Annotated, Literal

from pydantic import Field, StrictStr

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import OutPort
from grafy_core.plugins import NodeCachePolicy

from grafy_plugin_typesafe.artifacts import QUESTION
from grafy_plugin_typesafe.connection import QuestionId, raise_shown
from grafy_plugin_typesafe.declaration import TYPESAFE
from grafy_plugin_typesafe.limits import MAX_CHOICE_OPTIONS, MAX_SCORE_LEVELS
from grafy_plugin_typesafe.models import QuestionPayload
from grafy_plugin_typesafe.parsing import (
    JsonValue,
    parse_options,
    question_body,
    require_instructions,
)


class QuestionConfig(NodeConfig):
    question_id: QuestionId = Field(
        description=(
            "Name that Decide and Combine scores use to find this answer. "
            "It is not sent to the model."
        ),
    )
    kind: Literal["noul", "choice", "score"] = Field(
        default="noul",
        description=(
            "noul: the probability that the answer is yes. choice: one option "
            "from a set. score: a position on ordered levels."
        ),
    )
    instructions: StrictStr = Field(
        description=(
            "The question, with everything the model needs to answer it. Point "
            "at parts of a JSON state with backticked paths such as `ticket.body`."
        ),
        json_schema_extra={"format": "textarea"},
    )
    instructions_form: Literal["text", "json"] = Field(
        default="text",
        description=(
            "Send the instructions as plain text, or parse them as a JSON "
            "string, object, or array."
        ),
    )
    yes_means: StrictStr = Field(
        default="",
        description="Noul only. Optional description of a yes answer.",
    )
    no_means: StrictStr = Field(
        default="",
        description="Noul only. Optional description of a no answer.",
    )
    options: list[StrictStr] = Field(
        default_factory=list,
        max_length=MAX_CHOICE_OPTIONS,
        description=(
            "Choice only. One option per entry: a label, or a label, a colon, "
            "and its description. Labels cannot contain colons."
        ),
    )
    levels: list[StrictStr] = Field(
        default_factory=list,
        max_length=MAX_SCORE_LEVELS,
        description="Score only. 2 to 10 level descriptions, lowest first.",
    )


class QuestionInput(NodeInput):
    pass


class QuestionOutput(NodeOutput):
    question: Annotated[
        QuestionPayload,
        OutPort(QUESTION),
        Field(description="One question. Collect several into a stack for Evaluate."),
    ]


def build_question(config: QuestionConfig) -> QuestionPayload:
    yes_means = _optional_text(config.yes_means)
    no_means = _optional_text(config.no_means)
    if config.kind != "noul" and (yes_means or no_means):
        raise ValueError("yes_means and no_means apply only to noul questions")
    if config.kind != "choice" and config.options:
        raise ValueError("options apply only to choice questions")
    if config.kind != "score" and config.levels:
        raise ValueError("levels apply only to score questions")

    criteria: JsonValue | None
    if config.kind == "noul":
        criteria = _noul_criteria(yes_means, no_means)
    elif config.kind == "choice":
        if len(config.options) < 2:
            raise ValueError("A choice question needs at least two options")
        criteria = parse_options(config.options)
    else:
        criteria = _score_levels(config.levels)

    return QuestionPayload(
        question_id=config.question_id,
        kind=config.kind,
        body=question_body(
            kind=config.kind,
            instructions=require_instructions(
                config.instructions,
                form=config.instructions_form,
            ),
            criteria=criteria,
        ),
    )


def _optional_text(value: str) -> str | None:
    return None if value.strip() == "" else value


def _noul_criteria(yes_means: str | None, no_means: str | None) -> JsonValue | None:
    criteria: dict[str, JsonValue] = {}
    if yes_means is not None:
        criteria["true"] = yes_means
    if no_means is not None:
        criteria["false"] = no_means
    return criteria or None


def _score_levels(levels: list[str]) -> list[JsonValue]:
    for index, level in enumerate(levels):
        if level.strip() == "":
            raise ValueError(f"Score level {index} must not be blank")
    return list[JsonValue](levels)


@TYPESAFE.function_node(
    operator_id="typesafe.question",
    version=1,
    title="Question",
    cache_policy=NodeCachePolicy.EXACT,
)
async def question_node(
    config: QuestionConfig, inputs: QuestionInput
) -> QuestionOutput:
    """Builds one noul, choice, or score question from its settings."""

    del inputs
    try:
        return QuestionOutput(question=build_question(config))
    except ValueError as exc:
        raise_shown(exc)
