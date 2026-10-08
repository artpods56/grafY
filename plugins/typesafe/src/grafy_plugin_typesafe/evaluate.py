from collections.abc import Sequence
from typing import Annotated, Literal, final, override

from pydantic import Field, StrictStr

from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import NodeInput, NodeOutput
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.plugins import PluginRuntimeContext
from grafy_core.ports.node_secrets import NodeSecretResolverPort

from grafy_plugin_typesafe.artifacts import EVALUATION, QUESTION
from grafy_plugin_typesafe.connection import (
    API_CAPABILITIES,
    API_EGRESS,
    API_SECRET,
    TypeSafeConnectionConfig,
    raise_shown,
    resolve_api_key,
)
from grafy_plugin_typesafe.declaration import TYPESAFE
from grafy_plugin_typesafe.limits import MAX_QUESTIONS
from grafy_plugin_typesafe.models import EvaluationPayload, QuestionPayload
from grafy_plugin_typesafe.parsing import state_content
from grafy_plugin_typesafe.service import TypeSafePort


def build_evaluate_node(context: PluginRuntimeContext) -> "EvaluateNode":
    from grafy_plugin_typesafe.sdk import SdkTypeSafeClient

    return EvaluateNode(client=SdkTypeSafeClient(), node_secrets=context.node_secrets)


class EvaluateConfig(TypeSafeConnectionConfig):
    state_form: Literal["text", "json"] = Field(
        default="text",
        description="Send the state as plain text, or parse it as a JSON object or array.",
    )


class EvaluateInput(NodeInput):
    state: Annotated[
        StrictStr,
        InPort(TEXT_VALUE),
        Field(description="Text or JSON that every question is asked about."),
    ]
    questions: Annotated[
        list[QuestionPayload],
        InPort(QUESTION),
        Field(
            description=(
                "Questions asked together in one request. Collect Question "
                "outputs into a stack and connect it here."
            )
        ),
    ]


class EvaluateOutput(NodeOutput):
    evaluation: Annotated[
        EvaluationPayload,
        OutPort(EVALUATION),
        Field(description="Model, usage, and one answer per question."),
    ]


def check_batch(questions: Sequence[QuestionPayload]) -> list[QuestionPayload]:
    if not questions:
        raise ValueError("Evaluate needs at least one question")
    if len(questions) > MAX_QUESTIONS:
        raise ValueError(
            f"Evaluate accepts at most {MAX_QUESTIONS} questions in one request"
        )
    seen: set[str] = set()
    for question in questions:
        if question.question_id in seen:
            raise ValueError(
                f"Question id {question.question_id!r} is used twice. Each "
                "question in one request needs its own id."
            )
        seen.add(question.question_id)
    return list(questions)


@TYPESAFE.node(
    operator_id="typesafe.evaluate",
    version=1,
    title="Evaluate",
    factory=build_evaluate_node,
    required_capabilities=API_CAPABILITIES,
    secret_inputs=API_SECRET,
    http_egress=API_EGRESS,
)
@final
class EvaluateNode(Node[EvaluateConfig, EvaluateInput, EvaluateOutput]):
    """Asks every connected question about one state in a single TypeSafe request."""

    def __init__(
        self,
        *,
        client: TypeSafePort,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._client = client
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: EvaluateConfig,
        inputs: EvaluateInput,
        /,
    ) -> EvaluateOutput:
        try:
            state = state_content(inputs.state, form=config.state_form)
            questions = check_batch(inputs.questions)
        except ValueError as exc:
            raise_shown(exc)
        api_key = await resolve_api_key(
            context=context,
            config=config,
            node_secrets=self._node_secrets,
        )
        count = len(questions)
        await context.progress(
            f"Asking TypeSafe {count} question{'' if count == 1 else 's'}"
        )
        evaluation = await self._client.evaluate(
            api_key=api_key,
            config=config,
            state=state,
            questions=questions,
        )
        return EvaluateOutput(evaluation=evaluation)
