import math
from typing import Annotated

from pydantic import Field, StrictStr

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.nodes import InPort, OutPort
from grafy_core.plugins import NodeCachePolicy

from grafy_plugin_typesafe.artifacts import COMPOSITE_SCORE, EVALUATION
from grafy_plugin_typesafe.connection import raise_shown
from grafy_plugin_typesafe.declaration import TYPESAFE
from grafy_plugin_typesafe.lookup import find_score
from grafy_plugin_typesafe.models import (
    CompositeScorePayload,
    EvaluationPayload,
    ScoreComponent,
)
from grafy_plugin_typesafe.parsing import require_question_id

MAX_WEIGHT = 1_000_000
WEIGHTED_ID_PATTERN = r"^[A-Za-z_][A-Za-z0-9_-]*(\s*:\s*[0-9]+(\.[0-9]+)?)?$"

WeightedScoreId = Annotated[
    StrictStr,
    Field(min_length=1, max_length=160, pattern=WEIGHTED_ID_PATTERN),
]


class CombineScoresConfig(NodeConfig):
    scores: list[WeightedScoreId] = Field(
        min_length=1,
        max_length=64,
        description=(
            "Score ids to combine. Add a relative weight after a colon, such as "
            "urgency: 3. An id without a weight counts 1."
        ),
    )


class CombineScoresInput(NodeInput):
    evaluation: Annotated[
        EvaluationPayload,
        InPort(EVALUATION),
        Field(description="Evaluation that holds the score answers."),
    ]


class CombineScoresOutput(NodeOutput):
    score: Annotated[
        CompositeScorePayload,
        OutPort(COMPOSITE_SCORE),
        Field(description="Weighted average of scores scaled to 0–1."),
    ]


def parse_weights(entries: list[str]) -> list[tuple[str, float]]:
    weights: list[tuple[str, float]] = []
    seen: set[str] = set()
    for entry in entries:
        name, separator, raw_weight = entry.partition(":")
        question_id = require_question_id(name.strip())
        weight = 1.0
        if separator:
            try:
                weight = float(raw_weight.strip())
            except ValueError:
                raise ValueError(
                    f"Weight for {question_id!r} must be a number"
                ) from None
        if not math.isfinite(weight) or not 0 < weight <= MAX_WEIGHT:
            raise ValueError(
                f"Weight for {question_id!r} must be greater than 0 and at most "
                f"{MAX_WEIGHT}"
            )
        if question_id in seen:
            raise ValueError(f"Score {question_id!r} appears twice")
        seen.add(question_id)
        weights.append((question_id, weight))
    return weights


def combine_scores(
    evaluation: EvaluationPayload,
    weights: list[tuple[str, float]],
) -> CompositeScorePayload:
    total = sum(weight for _, weight in weights)
    components: list[ScoreComponent] = []
    value = 0.0
    for question_id, weight in weights:
        answer = find_score(evaluation, question_id)
        span = len(answer.levels) - 1
        normalized = answer.score / span
        share = weight / total
        value += share * normalized
        components.append(
            ScoreComponent(
                question_id=question_id,
                score=answer.score,
                level_span=span,
                normalized=normalized,
                weight=weight,
                share=share,
            )
        )
    return CompositeScorePayload(value=value, components=components)


@TYPESAFE.function_node(
    operator_id="typesafe.score.combine",
    version=1,
    title="Combine scores",
    cache_policy=NodeCachePolicy.EXACT,
)
async def combine_scores_node(
    config: CombineScoresConfig,
    inputs: CombineScoresInput,
) -> CombineScoresOutput:
    """Scales each score to 0–1 and averages them with your weights. Runs locally."""

    try:
        return CombineScoresOutput(
            score=combine_scores(inputs.evaluation, parse_weights(config.scores))
        )
    except ValueError as exc:
        raise_shown(exc)
