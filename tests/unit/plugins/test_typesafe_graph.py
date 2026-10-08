"""A collected stack of Question outputs feeds one Evaluate request."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Never

from pydantic import SecretStr

from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunInputPlugRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.plugins.runtime.admission import ReleaseExecutionAdmission
from grafy_api.v1.models import ArtifactTypeBindingModel, ArtifactTypeKeyResponse
from grafy_core.application.modules import ModuleLibraryService
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.ports.modules import GraphModuleExecutionResult
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, JsonObject
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
from grafy_core.nodes import Node, NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.invocation import InvocationMode
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
    TEST_BUILD_DIGEST,
    TEST_SYSTEM_PLUGINS,
    build_explicit_plugin_registry,
    build_selected_system_plugin_deployment,
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


def _unused_saved_graph_uow() -> Never:
    raise AssertionError("The compiler unexpectedly queried saved graphs")


class _UnusedModuleExecutor:
    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        _inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        raise AssertionError("The compiler unexpectedly executed a module")


def _node(node_id: str, operator_id: str, **fields: object) -> RunNodeRequest:
    return RunNodeRequest.model_validate(
        {
            "kind": "builtin",
            "id": node_id,
            "operator_id": operator_id,
            "operator_version": 1,
            **fields,
        }
    )


async def test_compiler_accepts_a_question_stack_and_asks_once(
    tmp_path: Path,
) -> None:
    registry = _registry()
    deployment = build_selected_system_plugin_deployment()
    compiler = GraphCompiler(
        plugin_registry=registry,
        plugin_context=_plugin_context(tmp_path),
        module_library=ModuleLibraryService(_unused_saved_graph_uow, registry),
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        plugin_release_lookup=deployment.release_lookup,
        release_admission=ReleaseExecutionAdmission(
            isolated_adapter_available=False,
            runtime_profile=None,
        ),
        build_digest=TEST_BUILD_DIGEST,
    )
    request = RunRequest(
        nodes=[
            _node("doc", "text.input", config={"text": "I was charged twice."}),
            _node(
                "billing",
                "typesafe.question",
                config={"question_id": "billing", "instructions": "Billing?"},
            ),
            _node(
                "tone",
                "typesafe.question",
                config={
                    "question_id": "tone",
                    "kind": "choice",
                    "instructions": "Tone?",
                    "options": ["calm", "angry"],
                },
            ),
            _node(
                "stack",
                "test.sequence.collect",
                input_plugs=[
                    RunInputPlugRequest(id="first", port="items"),
                    RunInputPlugRequest(id="second", port="items"),
                ],
                artifact_type_bindings=[
                    ArtifactTypeBindingModel(
                        variable="T",
                        artifact_type=ArtifactTypeKeyResponse(
                            id="typesafe.question",
                            schema_version=1,
                        ),
                    )
                ],
            ),
            _node("evaluate", "typesafe.evaluate"),
            _node("decide", "typesafe.decide", config={"question_ids": ["billing"]}),
        ],
        edges=[
            RunEdgeRequest(
                from_node="billing",
                from_port="question",
                to_node="stack",
                to_port="items",
                to_plug="first",
            ),
            RunEdgeRequest(
                from_node="tone",
                from_port="question",
                to_node="stack",
                to_port="items",
                to_plug="second",
            ),
            RunEdgeRequest(
                from_node="doc", from_port="text", to_node="evaluate", to_port="state"
            ),
            RunEdgeRequest(
                from_node="stack",
                from_port="items",
                to_node="evaluate",
                to_port="questions",
            ),
            RunEdgeRequest(
                from_node="evaluate",
                from_port="evaluation",
                to_node="decide",
                to_port="evaluation",
            ),
        ],
    )

    compiled = await compiler.compile(
        request.model_copy(
            update={"nodes": [deployment.pin_node(node) for node in request.nodes]}
        ),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )

    evaluate = next(node for node in compiled.nodes if node.request.id == "evaluate")
    assert evaluate.invocation.mode is InvocationMode.ONCE
    assert [node.request.id for node in compiled.nodes][-2:] == ["evaluate", "decide"]


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
