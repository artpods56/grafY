"""Run synthetic TypeSafe workflows through Grafy's local artifact runtime."""

import argparse
import asyncio
from collections.abc import Mapping
import os
from pathlib import Path
import stat
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, SecretStr

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
)
from grafy_core.nodes import NodeExecutionContext, UserFacingNodeError
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.node_secrets import JsonValue, NodeSecretUnavailableError
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
from grafy_plugin_typesafe.models import (
    CompositeScorePayload,
    DecisionPayload,
    EvaluationPayload,
)
from grafy_storage import LocalFileObjectStore
from grafy_workbench.text import TEXT
from tests.support.scenarios.sequences import SEQUENCES


class ProcessKey:
    """A process-only secret boundary; credentials never enter graph artifacts."""

    def __init__(self, key: SecretStr | None) -> None:
        self._key = key
        self._revision = str(uuid4())

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        del workspace_id, graph_id, graph_revision, node_id
        if name != "api_key" or dependencies != {"base_url": "https://api.typesafe.ai"}:
            raise NodeSecretUnavailableError("Unexpected TypeSafe secret request")
        if self._key is None:
            raise NodeSecretUnavailableError("No TypeSafe key configured")
        return self._key

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, graph_id, graph_revision, node_id, name, dependencies
        return self._revision


class SmokeResult(BaseModel):
    case: str
    status: Literal["prepared", "passed"]
    question_count: int
    evaluation: EvaluationPayload | None = None
    billing_decision: DecisionPayload | None = None
    route_decision: DecisionPayload | None = None
    combined_score: CompositeScorePayload | None = None


class LocalGraph:
    def __init__(self, workspace: Path, key: SecretStr | None) -> None:
        self.workspace_id = uuid4()
        self.registry = PluginRegistry()
        for plugin in (TEXT, SEQUENCES, TYPESAFE):
            self.registry.install(plugin)
        self.registry.freeze()
        self.context = PluginRuntimeContext(
            workspace=workspace,
            storage=LocalFileObjectStore(workspace / "objects"),
            uow=InMemoryUnitOfWork(),
            bucket="smoke",
            node_secrets=ProcessKey(key),
        )
        self.resolvers = ResolverRegistry(
            list(self.registry.build_resolvers(self.context))
        )
        self.runtime = NodeRuntime(
            materializer=InputMaterializer(self.resolvers),
            persister=OutputPersister(
                ArtifactWriterRegistry(list(self.registry.build_writers(self.context)))
            ),
        )

    async def run(
        self,
        operator: str,
        node_id: str,
        inputs: Mapping[str, object],
        config: JsonObject | None = None,
        bindings: Mapping[str, ArtifactTypeKey] | None = None,
    ) -> PersistedNodeOutput:
        output = await self.runtime.run_node(
            self.registry.build_node(operator, 1, self.context),
            NodeExecutionContext(workspace_id=self.workspace_id, node_id=node_id),
            inputs,
            config,
            artifact_type_bindings=bindings,
        )
        if not isinstance(output, PersistedNodeOutput):
            raise RuntimeError(f"{node_id} did not persist its output")
        return output


def single_ref(output: PersistedNodeOutput, port: str) -> ArtifactRef:
    ref = output[port]
    if not isinstance(ref, ArtifactRef):
        raise RuntimeError(f"Expected a single artifact on {port}")
    return ref


async def run_case(
    graph: LocalGraph,
    *,
    case: str,
    state: str,
    state_form: Literal["text", "json"],
    expected_route: str,
    expected_billing: str,
    model: str,
    prepare_only: bool,
) -> SmokeResult:
    document = await graph.run("text.input", case + "-text", {}, {"text": state})
    configurations: list[JsonObject] = [
        {
            "question_id": "billing",
            "instructions": "Does the customer request help with a charge, payment, or refund?",
        },
        {
            "question_id": "route",
            "kind": "choice",
            "instructions": "Which support queue matches this customer message?",
            "options": [
                "billing: charges, payments, and refunds",
                "technical: software outages and malfunctioning services",
                "other: everything else",
            ],
        },
        {
            "question_id": "urgency",
            "kind": "score",
            "instructions": "How urgent is the requested help?",
            "levels": [
                "No help is requested",
                "Help can wait several days",
                "Help is needed today",
                "An ongoing critical issue needs immediate help",
            ],
        },
        {
            "question_id": "impact",
            "kind": "score",
            "instructions": "How much does the reported problem affect the customer?",
            "levels": [
                "No problem reported",
                "Minor inconvenience",
                "Financial loss or significant disruption",
                "Business operations are stopped",
            ],
        },
    ]
    question_refs: list[ArtifactRef] = []
    for config in configurations:
        output = await graph.run(
            "typesafe.question", case + "-" + str(config["question_id"]), {}, config
        )
        question_refs.append(single_ref(output, "question"))
    collected = await graph.run(
        "test.sequence.collect",
        case + "-stack",
        {"items": question_refs},
        bindings={"T": QUESTION.key},
    )
    sequence = collected["items"]
    if not isinstance(sequence, ArtifactRefSequence) or len(sequence.item_refs) != 4:
        raise RuntimeError("Collect did not preserve all four questions")
    if prepare_only:
        return SmokeResult(case=case, status="prepared", question_count=4)
    evaluated = await graph.run(
        "typesafe.evaluate",
        case + "-evaluate",
        {
            "state": single_ref(document, "text"),
            "questions": sequence,
        },
        {"model": model, "state_form": state_form, "max_retries": 0},
    )
    evaluation_ref = single_ref(evaluated, "evaluation")
    billing = await graph.run(
        "typesafe.decide",
        case + "-billing-decision",
        {"evaluation": evaluation_ref},
        {"question_ids": ["billing"]},
    )
    route = await graph.run(
        "typesafe.decide",
        case + "-route-decision",
        {"evaluation": evaluation_ref},
        {"question_ids": ["route"], "minimum_confidence": 0.0},
    )
    combined = await graph.run(
        "typesafe.score.combine",
        case + "-combined",
        {"evaluation": evaluation_ref},
        {"scores": ["urgency: 3", "impact"]},
    )
    evaluation = await graph.resolvers.resolve(
        evaluation_ref, EvaluationPayload, graph.workspace_id
    )
    billing_decision = await graph.resolvers.resolve(
        single_ref(billing, "decision"), DecisionPayload, graph.workspace_id
    )
    route_decision = await graph.resolvers.resolve(
        single_ref(route, "decision"), DecisionPayload, graph.workspace_id
    )
    combined_score = await graph.resolvers.resolve(
        single_ref(combined, "score"), CompositeScorePayload, graph.workspace_id
    )
    if (
        len(evaluation.nouls) != 1
        or len(evaluation.choices) != 1
        or len(evaluation.scores) != 2
    ):
        raise RuntimeError(
            f"{case}: evaluation did not contain the four requested answers"
        )
    if (
        billing_decision.outcome != expected_billing
        or route_decision.outcome != expected_route
    ):
        raise RuntimeError(
            f"{case}: expected billing={expected_billing}, route={expected_route}; got billing={billing_decision.outcome}, route={route_decision.outcome}"
        )
    if not 0 <= combined_score.value <= 1:
        raise RuntimeError(f"{case}: combined score is outside 0–1")
    return SmokeResult(
        case=case,
        status="passed",
        question_count=4,
        evaluation=evaluation,
        billing_decision=billing_decision,
        route_decision=route_decision,
        combined_score=combined_score,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--key-file",
        type=Path,
        help="Protected file containing the TypeSafe key; otherwise use TYPESAFE_API_KEY",
    )
    _ = parser.add_argument("--model", default="jev-latest")
    _ = parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Build and collect real artifacts without calling TypeSafe",
    )
    _ = parser.add_argument(
        "--output", type=Path, default=Path(".grafy-artifacts/typesafe-smoke")
    )
    args = parser.parse_args()
    key: SecretStr | None = None
    if not args.prepare_only:
        if args.key_file is not None:
            key_path = Path(args.key_file)
            if stat.S_IMODE(key_path.stat().st_mode) & 0o077:
                parser.error(
                    "The key file must not be readable by other users; run chmod 600 on it"
                )
            key = SecretStr(key_path.read_text().strip())
        else:
            value = os.environ.get("TYPESAFE_API_KEY", "").strip()
            if value:
                key = SecretStr(value)
        if key is None or not key.get_secret_value():
            parser.error(
                "Set TYPESAFE_API_KEY or provide --key-file to make live calls"
            )
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    graph = LocalGraph(output_dir, key)
    cases: list[tuple[str, str, Literal["text", "json"], str, str]] = [
        (
            "billing-text",
            "I was charged twice for my subscription. Please refund the duplicate payment.",
            "text",
            "billing",
            "yes",
        ),
        (
            "outage-json",
            '{"customer_message":"Our production API has been down for 30 minutes. All orders are failing. Restore the service immediately."}',
            "json",
            "technical",
            "no",
        ),
    ]
    for name, state, form, expected_route, expected_billing in cases:
        result = await run_case(
            graph,
            case=name,
            state=state,
            state_form=form,
            expected_route=expected_route,
            expected_billing=expected_billing,
            model=args.model,
            prepare_only=args.prepare_only,
        )
        _ = (output_dir / (name + ".json")).write_text(
            result.model_dump_json(indent=2) + "\n"
        )
        print(f"{name}: {result.status}, {result.question_count} questions")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except UserFacingNodeError as exc:
        raise SystemExit(str(exc)) from None
