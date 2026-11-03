"""A collected stack of Question outputs feeds one Evaluate request."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, JsonObject
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_plugin_typesafe import TYPESAFE
from grafy_plugin_typesafe.artifacts import QUESTION
from grafy_plugin_typesafe.connection import TypeSafeConnectionConfig
from grafy_plugin_typesafe.evaluate import EvaluateNode
from grafy_plugin_typesafe.models import (
    CompositeScorePayload,
    DecisionPayload,
    EvaluationPayload,
    QuestionPayload,
)
from grafy_plugin_typesafe.parsing import JsonContent
from grafy_storage import LocalFileObjectStore
from tests.support.system_plugins import (
    TEST_SYSTEM_PLUGINS,
    build_explicit_plugin_registry,
)
from tests.unit.plugins.test_typesafe_nodes import (
    WORKSPACE_ID,
    FakeSecrets,
    sample_evaluation,
)


def _ref(output: PersistedNodeOutput, port: str) -> ArtifactRef:
    ref = output[port]
    assert isinstance(ref, ArtifactRef)
    return ref


def _registry() -> PluginRegistry:
    return build_explicit_plugin_registry((*TEST_SYSTEM_PLUGINS, TYPESAFE))


def _plugin_context(tmp_path: Path) -> PluginRuntimeContext:
    return PluginRuntimeContext(
        workspace=tmp_path,
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="test-artifacts",
    )


class RecordingClient:
    def __init__(self) -> None:
        self.requests: list[tuple[JsonContent, list[str]]] = []

    async def evaluate(
        self,
        *,
        api_key: SecretStr,
        config: TypeSafeConnectionConfig,
        state: JsonContent,
        questions: Sequence[QuestionPayload],
    ) -> EvaluationPayload:
        del api_key, config
        self.requests.append((state, [question.question_id for question in questions]))
        return sample_evaluation()


async def test_runtime_materializes_a_question_stack_for_one_request(
    tmp_path: Path,
) -> None:
    registry = _registry()
    context = _plugin_context(tmp_path)
    resolvers = ResolverRegistry(list(registry.build_resolvers(context)))
    writers = ArtifactWriterRegistry()
    for writer in registry.build_writers(context):
        writers.register(writer)
    runtime = NodeRuntime(
        materializer=InputMaterializer(resolvers),
        persister=OutputPersister(writers),
    )

    async def run(
        node: Node[Any, Any, Any],
        node_id: str,
        inputs: dict[str, object],
        config: JsonObject | None = None,
    ) -> PersistedNodeOutput:
        output = await runtime.run_node(
            node,
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id=node_id),
            inputs,
            config,
        )
        assert isinstance(output, PersistedNodeOutput)
        return output

    def build(operator_id: str) -> Node[Any, Any, Any]:
        return registry.build_node(operator_id, 1, context)

    document = await run(build("text.input"), "doc", {}, {"text": "Charged twice."})
    billing = await run(
        build("typesafe.question"),
        "billing",
        {},
        {"question_id": "billing", "instructions": "Billing?"},
    )
    tone = await run(
        build("typesafe.question"),
        "tone",
        {},
        {
            "question_id": "tone",
            "kind": "choice",
            "instructions": "Tone?",
            "options": ["calm", "angry"],
        },
    )
    client = RecordingClient()
    evaluated = await run(
        EvaluateNode(client=client, node_secrets=FakeSecrets(SecretStr("key"))),
        "evaluate",
        {
            "state": _ref(document, "text"),
            "questions": ArtifactRefSequence.from_key(
                key=QUESTION.key,
                item_refs=[_ref(billing, "question"), _ref(tone, "question")],
            ),
        },
    )
    decided = await run(
        build("typesafe.decide"),
        "decide",
        {"evaluation": _ref(evaluated, "evaluation")},
        {"question_ids": ["billing"]},
    )
    combined = await run(
        build("typesafe.score.combine"),
        "combine",
        {"evaluation": _ref(evaluated, "evaluation")},
        {"scores": ["python: 4", "leadership"]},
    )

    assert client.requests == [("Charged twice.", ["billing", "tone"])]
    decision = await resolvers.resolve(
        _ref(decided, "decision"), DecisionPayload, WORKSPACE_ID
    )
    score = await resolvers.resolve(
        _ref(combined, "score"), CompositeScorePayload, WORKSPACE_ID
    )
    assert (decision.disposition, decision.outcome) == ("act", "yes")
    assert abs(score.value - 0.65) < 1e-9
