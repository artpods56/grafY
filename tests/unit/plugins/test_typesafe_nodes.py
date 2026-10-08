from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError

from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.nodes import NodeExecutionContext, UserFacingNodeError
from grafy_core.plugins import NodeHttpEgressInput
from grafy_core.ports.node_secrets import JsonValue
from grafy_plugin_typesafe.combine import (
    CombineScoresConfig,
    CombineScoresInput,
    CombineScoresOutput,
    parse_weights,
)
from grafy_plugin_typesafe.connection import TypeSafeConnectionConfig
from grafy_plugin_typesafe.decide import DecideConfig, DecideInput, DecideOutput
from grafy_plugin_typesafe.declaration import TYPESAFE
from grafy_plugin_typesafe.evaluate import EvaluateConfig, EvaluateInput, EvaluateNode
from grafy_plugin_typesafe.models import (
    ChoiceAnswerPayload,
    EvaluationPayload,
    NoulAnswerPayload,
    QuestionPayload,
    ScoreAnswerPayload,
    UsagePayload,
)
from grafy_plugin_typesafe.parsing import JsonContent
from grafy_plugin_typesafe.question import (
    QuestionConfig,
    QuestionInput,
    QuestionOutput,
    build_question,
)


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000911")


class FakeSecrets:
    def __init__(self, value: SecretStr) -> None:
        self._value = value
        self.dependencies: Mapping[str, JsonValue] | None = None

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
        assert workspace_id == WORKSPACE_ID
        assert name == "api_key"
        self.dependencies = dependencies
        del graph_id, graph_revision, node_id
        return self._value

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
        return "0" * 64


class FakeClient:
    def __init__(self, evaluation: EvaluationPayload) -> None:
        self.evaluation = evaluation
        self.calls = 0
        self.api_key: SecretStr | None = None
        self.question_ids: list[str] | None = None
        self.state: JsonContent | None = None

    async def evaluate(
        self,
        *,
        api_key: SecretStr,
        config: TypeSafeConnectionConfig,
        state: JsonContent,
        questions: Sequence[QuestionPayload],
    ) -> EvaluationPayload:
        del config
        self.calls += 1
        self.api_key = api_key
        self.question_ids = [question.question_id for question in questions]
        self.state = state
        return self.evaluation


def sample_evaluation() -> EvaluationPayload:
    return EvaluationPayload(
        requested_model="jev-latest",
        model="jev-1.13.0",
        base_url="https://api.typesafe.ai",
        usage=UsagePayload(input_tokens=20, output_tokens=4),
        nouls=[
            NoulAnswerPayload(question_id="billing", noul=0.91),
            NoulAnswerPayload(question_id="pii", noul=0.2),
        ],
        choices=[
            ChoiceAnswerPayload(
                question_id="tone",
                choice="angry",
                confidence=0.84,
                probabilities={"calm": 0.1, "angry": 0.9},
            ),
            ChoiceAnswerPayload(
                question_id="team",
                choice="support",
                confidence=0.6,
                probabilities={"sales": 0.4, "support": 0.6},
            ),
        ],
        scores=[
            ScoreAnswerPayload(
                question_id="python",
                score=3.0,
                confidence=0.7,
                levels=["none", "some", "daily", "deep", "expert"],
                probabilities={"0": 0.0, "1": 0.0, "2": 0.1, "3": 0.8, "4": 0.1},
            ),
            ScoreAnswerPayload(
                question_id="leadership",
                score=1.0,
                confidence=0.6,
                levels=["none", "some", "daily", "deep", "expert"],
                probabilities={"0": 0.2, "1": 0.6, "2": 0.2, "3": 0.0, "4": 0.0},
            ),
        ],
    )


def _question(question_id: str, **settings: object) -> QuestionPayload:
    return build_question(
        QuestionConfig.model_validate(
            {"question_id": question_id, "instructions": "Is it?", **settings}
        )
    )


async def _run_local[T: NodeOutput](
    operator_id: str,
    output_model: type[T],
    config: NodeConfig,
    inputs: NodeInput,
) -> T:
    registration = next(item for item in TYPESAFE.nodes if item.key == (operator_id, 1))
    output = await registration.node_class().run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID),
        config,
        inputs,
    )
    assert isinstance(output, output_model)
    return output


def test_plugin_ships_four_nodes_and_four_artifact_types() -> None:
    manifest = PluginCatalogManifest.from_plugin(TYPESAFE)

    assert {(node.operator_id, node.operator_version) for node in manifest.nodes} == {
        ("typesafe.question", 1),
        ("typesafe.evaluate", 1),
        ("typesafe.decide", 1),
        ("typesafe.score.combine", 1),
    }
    assert {artifact.key.id for artifact in manifest.artifact_types} == {
        "typesafe.question",
        "typesafe.evaluation",
        "typesafe.decision",
        "typesafe.composite_score",
    }


def _form_editable(schema: dict[str, object]) -> bool:
    kind = schema.get("type")
    if kind in ("string", "number", "integer", "boolean"):
        return True
    items = schema.get("items")
    return (
        kind == "array"
        and isinstance(items, dict)
        and cast(dict[str, object], items).get("type") == "string"
    )


def test_every_setting_is_editable_in_the_workbench_form() -> None:
    # The workbench form renders scalars, enums, and lists of strings. A list of
    # objects would be dropped from the form and could never be filled in.
    for node in PluginCatalogManifest.from_plugin(TYPESAFE).nodes:
        properties = cast(
            dict[str, dict[str, object]], node.config_schema.get("properties", {})
        )
        for name, schema in properties.items():
            assert _form_editable(schema), f"{node.operator_id}.{name}"


async def test_question_builds_each_kind_in_api_shape() -> None:
    noul = await _run_local(
        "typesafe.question",
        QuestionOutput,
        QuestionConfig(
            question_id="billing",
            instructions="Refund?",
            yes_means="The customer asks for money back.",
            no_means="   ",
        ),
        QuestionInput(),
    )
    choice = _question(
        "tone",
        kind="choice",
        options=["calm", "angry: Strong language: shouting", "other:"],
    )
    score = _question(
        "urgency",
        kind="score",
        instructions='{"question": "Urgent?"}',
        instructions_form="json",
        levels=["can wait", "today"],
    )

    assert noul.question.kind == "noul"
    assert noul.question.body == (
        '{"type":"noul","instructions":"Refund?",'
        '"criteria":{"true":"The customer asks for money back."}}'
    )
    assert _question("plain").body == '{"type":"noul","instructions":"Is it?"}'
    assert choice.body == (
        '{"type":"choice","instructions":"Is it?","criteria":'
        '{"calm":null,"angry":"Strong language: shouting","other":null}}'
    )
    assert score.body == (
        '{"type":"score","instructions":{"question":"Urgent?"},'
        '"criteria":["can wait","today"]}'
    )


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"options": ["a", "b"]}, "options apply only to choice"),
        (
            {"kind": "choice", "options": ["a", "b"], "levels": ["x", "y"]},
            "levels apply only",
        ),
        (
            {"kind": "score", "levels": ["x", "y"], "yes_means": "yes"},
            "apply only to noul",
        ),
        ({"kind": "choice", "options": ["only"]}, "at least two options"),
        ({"kind": "choice", "options": ["a", "a: again"]}, "appears twice"),
        ({"kind": "choice", "options": ["a", ": no label"]}, "non-empty"),
        ({"kind": "score", "levels": ["one"]}, "2 to 10"),
        ({"kind": "score", "levels": ["low", " "]}, "must not be blank"),
        ({"instructions": "  "}, "must not be blank"),
        ({"instructions": "not json", "instructions_form": "json"}, "valid JSON"),
    ],
)
async def test_question_reports_settings_that_do_not_fit_its_kind(
    settings: dict[str, object],
    message: str,
) -> None:
    config = QuestionConfig.model_validate(
        {"question_id": "check", "instructions": "Is it?", **settings}
    )
    with pytest.raises(UserFacingNodeError, match=message):
        await _run_local("typesafe.question", QuestionOutput, config, QuestionInput())


def test_question_id_must_be_usable_by_later_nodes() -> None:
    with pytest.raises(ValidationError):
        QuestionConfig(question_id="1st check", instructions="Is it?")


def test_evaluate_declares_secret_egress_and_a_question_sequence_input() -> None:
    registration = next(
        item for item in TYPESAFE.nodes if item.key == ("typesafe.evaluate", 1)
    )
    contract = next(
        node
        for node in PluginCatalogManifest.from_plugin(TYPESAFE).nodes
        if node.operator_id == "typesafe.evaluate"
    )
    ports = {port.name: port for port in contract.inputs}

    assert registration.required_capabilities == (
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    )
    assert registration.secret_inputs[0].name == "api_key"
    assert registration.secret_inputs[0].config_dependencies == ("base_url",)
    assert registration.http_egress is not None
    assert registration.http_egress.configured_inputs == (
        NodeHttpEgressInput(config_field="base_url"),
    )
    # A collected stack of questions is a sequence, so the port must take one.
    questions = ports["questions"]
    assert questions.artifact_type is not None
    assert questions.artifact_type.id == "typesafe.question"
    assert [shape.value for shape in questions.accepted_shapes] == ["many"]
    assert not questions.instance_plugs
    state = ports["state"]
    assert state.artifact_type is not None
    assert state.artifact_type.id == "scalar.text"
    with pytest.raises(ValidationError):
        TypeSafeConnectionConfig(base_url="http://example.com")


def _context() -> NodeExecutionContext:
    return NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        secret_graph_id=uuid4(),
        secret_graph_revision=2,
        node_id="evaluate-1",
    )


async def test_evaluate_sends_the_state_and_every_question_in_one_request() -> None:
    secret = SecretStr("typesafe-test-key")
    secrets = FakeSecrets(secret)
    client = FakeClient(sample_evaluation())
    node = EvaluateNode(client=client, node_secrets=secrets)

    output = await node.run(
        _context(),
        EvaluateConfig(),
        EvaluateInput(
            state="I was charged twice.",
            questions=[
                _question("billing"),
                _question("tone", kind="choice", options=["calm", "angry"]),
            ],
        ),
    )

    assert client.calls == 1
    assert client.api_key == secret
    assert secrets.dependencies == {"base_url": "https://api.typesafe.ai"}
    assert client.state == "I was charged twice."
    assert client.question_ids == ["billing", "tone"]
    assert output.evaluation.model == "jev-1.13.0"


async def test_evaluate_parses_json_state() -> None:
    client = FakeClient(sample_evaluation())
    node = EvaluateNode(client=client, node_secrets=FakeSecrets(SecretStr("key")))

    await node.run(
        _context(),
        EvaluateConfig(state_form="json"),
        EvaluateInput(
            state='{"ticket": ["refund", null]}',
            questions=[_question("billing")],
        ),
    )

    assert client.state == {"ticket": ["refund", None]}


@pytest.mark.parametrize(
    ("state", "state_form", "question_ids", "message"),
    [
        ("hello", "text", [], "at least one question"),
        ("hello", "text", ["billing", "billing"], "used twice"),
        ("   ", "text", ["billing"], "must not be blank"),
        ('"just text"', "json", ["billing"], "object or array"),
        ("not json", "json", ["billing"], "valid JSON"),
    ],
)
async def test_evaluate_rejects_bad_input_without_calling_typesafe(
    state: str,
    state_form: str,
    question_ids: list[str],
    message: str,
) -> None:
    client = FakeClient(sample_evaluation())
    node = EvaluateNode(client=client, node_secrets=FakeSecrets(SecretStr("key")))

    with pytest.raises(UserFacingNodeError, match=message):
        await node.run(
            _context(),
            EvaluateConfig.model_validate({"state_form": state_form}),
            EvaluateInput(
                state=state,
                questions=[_question(question_id) for question_id in question_ids],
            ),
        )
    assert client.calls == 0


async def _decide(**settings: object) -> DecideOutput:
    return await _run_local(
        "typesafe.decide",
        DecideOutput,
        DecideConfig.model_validate(settings),
        DecideInput(evaluation=sample_evaluation()),
    )


@pytest.mark.parametrize(
    ("probability", "outcome", "disposition"),
    [(0.2, "no", "act"), (0.5, "review", "review"), (0.8, "yes", "act")],
)
async def test_decide_noul_threshold_boundaries(
    probability: float,
    outcome: str,
    disposition: str,
) -> None:
    evaluation = EvaluationPayload(
        requested_model="jev-latest",
        model="jev-latest",
        base_url="https://api.typesafe.ai",
        usage=UsagePayload(),
        nouls=[NoulAnswerPayload(question_id="check", noul=probability)],
    )
    result = await _run_local(
        "typesafe.decide",
        DecideOutput,
        DecideConfig(question_ids=["check"]),
        DecideInput(evaluation=evaluation),
    )

    assert result.decision.outcome == outcome
    assert result.decision.disposition == disposition
    assert result.decision.signal == probability


async def test_decide_any_guards_and_all_requires_every_noul() -> None:
    guard = await _decide(question_ids=["pii", "billing"])
    every = await _decide(question_ids=["pii", "billing"], require="all")

    assert guard.decision.outcome == "yes"
    assert guard.decision.question_id == "billing"
    assert guard.decision.reason.startswith("Highest noul 'billing' is 0.910")
    assert every.decision.outcome == "no"
    assert every.decision.question_id == "pii"
    assert every.decision.reason.startswith("Lowest noul 'pii' is 0.200")


async def test_decide_accepts_or_reviews_a_choice() -> None:
    accepted = await _decide(
        question_ids=["tone"], minimum_confidence=0.8, allow=["angry"]
    )
    unsure = await _decide(question_ids=["tone"], minimum_confidence=0.9)
    outside = await _decide(question_ids=["tone"], allow=["calm"])

    assert accepted.decision.disposition == "act"
    assert accepted.decision.outcome == "angry"
    assert unsure.decision.disposition == "review"
    assert unsure.decision.outcome == "angry"
    assert outside.decision.disposition == "review"
    assert "allow list" in outside.decision.reason


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"question_ids": ["missing"]}, "no answer named 'missing'"),
        ({"question_ids": ["python"]}, "Use Combine scores"),
        ({"question_ids": ["billing", "tone"]}, "nouls or one choice, not both"),
        ({"question_ids": ["tone", "team"]}, "one choice at a time"),
        ({"question_ids": ["billing"], "allow": ["yes"]}, "allow applies only"),
    ],
)
async def test_decide_reports_answers_it_cannot_decide(
    settings: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(UserFacingNodeError, match=message):
        await _decide(**settings)


@pytest.mark.parametrize(
    "settings",
    [
        {"question_ids": []},
        {"question_ids": ["billing", "billing"]},
        {"question_ids": ["billing"], "yes_at": 0.5, "no_at": 0.5},
        {"question_ids": ["not an id"]},
    ],
)
def test_decide_config_rejects_unusable_rules(settings: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DecideConfig.model_validate(settings)


async def test_combine_scores_weights_normalized_scores() -> None:
    combined = await _run_local(
        "typesafe.score.combine",
        CombineScoresOutput,
        CombineScoresConfig(scores=["python: 4", "leadership"]),
        CombineScoresInput(evaluation=sample_evaluation()),
    )

    expected = (0.8 * (3 / 4)) + (0.2 * (1 / 4))
    assert abs(combined.score.value - expected) < 1e-9
    assert [component.weight for component in combined.score.components] == [4, 1]
    assert parse_weights(["a:0.5", "b : 2"]) == [("a", 0.5), ("b", 2.0)]


@pytest.mark.parametrize(
    ("scores", "message"),
    [
        (["python: 0"], "greater than 0"),
        (["python", "python: 2"], "appears twice"),
        (["billing"], "not a score"),
    ],
)
async def test_combine_scores_reports_unusable_weights(
    scores: list[str],
    message: str,
) -> None:
    with pytest.raises(UserFacingNodeError, match=message):
        await _run_local(
            "typesafe.score.combine",
            CombineScoresOutput,
            CombineScoresConfig(scores=scores),
            CombineScoresInput(evaluation=sample_evaluation()),
        )


def test_combine_scores_config_rejects_a_malformed_weight() -> None:
    with pytest.raises(ValidationError):
        CombineScoresConfig(scores=["python: heavy"])


@pytest.mark.parametrize(
    ("score", "probabilities"),
    [
        (2.1, {"0": 0.1, "1": 0.6, "2": 0.3}),
        (1.2, {"0": 0.1, "1": 0.9}),
        (1.2, {"0": 0.1, "1": 0.6, "3": 0.3}),
    ],
)
def test_score_artifact_rejects_inconsistent_rubric(
    score: float, probabilities: dict[str, float]
) -> None:
    with pytest.raises(ValidationError, match="declared level"):
        ScoreAnswerPayload(
            question_id="urgency",
            score=score,
            confidence=0.7,
            levels=["low", "mid", "high"],
            probabilities=probabilities,
        )
