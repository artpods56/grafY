from typing import cast

from pydantic import BaseModel

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, JsonObject

from grafy_plugin_typesafe.models import (
    CompositeScorePayload,
    DecisionPayload,
    EvaluationPayload,
    QuestionPayload,
)


def _spec(type_id: str, title: str, model: type[BaseModel]) -> ArtifactTypeSpec:
    return ArtifactTypeSpec(
        key=ArtifactTypeKey(type_id, 1),
        title=title,
        payload_schema=cast(JsonObject, model.model_json_schema()),
    )


QUESTION = _spec("typesafe.question", "TypeSafe question", QuestionPayload)
EVALUATION = _spec("typesafe.evaluation", "TypeSafe evaluation", EvaluationPayload)
DECISION = _spec("typesafe.decision", "TypeSafe decision", DecisionPayload)
COMPOSITE_SCORE = _spec(
    "typesafe.composite_score",
    "Composite score",
    CompositeScorePayload,
)
