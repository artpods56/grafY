from grafy_core.artifacts import Artifact, ArtifactTypeSpec
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver
from pydantic import BaseModel

from grafy_plugin_typesafe import combine, decide, evaluate, question
from grafy_plugin_typesafe.artifacts import (
    COMPOSITE_SCORE,
    DECISION,
    EVALUATION,
    QUESTION,
)
from grafy_plugin_typesafe.declaration import TYPESAFE
from grafy_plugin_typesafe.models import (
    CompositeScorePayload,
    DecisionPayload,
    EvaluationPayload,
    QuestionPayload,
)

_NODE_MODULES = (question, evaluate, decide, combine)


def _register[T: BaseModel](spec: ArtifactTypeSpec, model: type[T]) -> None:
    TYPESAFE.register(
        Artifact(
            spec=spec,
            resolver=lambda context, source=spec, target=model: InlineModelResolver(
                source=source.key,
                target=target,
                uow=context.uow,
            ),
            writer=lambda context, artifact_type=spec, payload=model: (
                InlineModelOutputWriter(
                    artifact_type=artifact_type.key,
                    model=payload,
                    uow=context.uow,
                )
            ),
        )
    )


_register(QUESTION, QuestionPayload)
_register(EVALUATION, EvaluationPayload)
_register(DECISION, DecisionPayload)
_register(COMPOSITE_SCORE, CompositeScorePayload)

__all__ = ["TYPESAFE"]
