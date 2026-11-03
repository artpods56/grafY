"""The fingerprint facts a Project document is fingerprinted with (ADR 0020).

The kernel asks three questions per node — what does it run, may its result be
reused, what credential state does it run under — and this module is where the
document stops being the only source of the answers. The cases below pin the two
rules that make a wrong answer dangerous: a Graph boundary has an identity of its
own and is always reusable, and an operator this build cannot describe stops the
Run instead of receiving a placeholder digest or a silent ``NEVER``.

The secret half is about identity rather than values: a revision is read by
``(project, graph, node)``, so a Graph called twice runs under one credential and
fingerprints one way, and a secret that has never been set is a revision of its
own instead of an absence. Real ``PluginRegistry``, real
``RegistryImplementationDigests`` and a real ``NodeSecretInput`` declaration answer
the questions; only the secret store is faked.
"""

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from grafy_api.runs.facts import UNAVAILABLE_SECRET_REVISION, ApplicationFacts
from grafy_api.runs.ports import RunRejectedError
from grafy_core.domain.graph_documents import GraphNode
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.implementation_identity import EXECUTION_EPOCH
from grafy_core.kernel.instances import ExpandedGraph, InstanceKey
from grafy_core.kernel.project import (
    GRAPH_INPUT_OPERATOR_ID,
    GRAPH_OUTPUT_OPERATOR_ID,
    GraphDefinition,
    ProjectDocument,
)
from grafy_core.plugins import NodeCachePolicy, UnknownOperatorError
from tests.unit.runs.fakes import (
    GHOST_OPERATOR,
    NEVER_OPERATOR,
    PROJECT_ID,
    SECRET_OPERATOR,
    VALUE_OPERATOR,
    WORKSPACE_ID,
    FakeCatalog,
    FakeSecretRevisionResolver,
    build_catalog,
    caller_graph,
    child_graph,
    document,
    edge,
    facts_factory,
    graph,
    main_graph,
    never_node,
    input_node,
    output_node,
    secret_node,
    value_node,
)


async def facts_for(
    catalog: FakeCatalog,
    project: ProjectDocument,
    secrets: FakeSecretRevisionResolver | None = None,
) -> ApplicationFacts:
    facts = await facts_factory(catalog, secrets).for_project(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        document=project,
    )
    assert isinstance(facts, ApplicationFacts)
    return facts


def expanded(project: ProjectDocument, graph_id: str = "main") -> ExpandedGraph:
    return expand_graph(project, graph_id, project_id=str(PROJECT_ID))


def instance(
    view: ExpandedGraph,
    node_id: str,
    call_path: Sequence[str] = (),
) -> InstanceKey:
    return next(
        key
        for key in view.instances
        if key.node_id == node_id and key.call_path == tuple(call_path)
    )


def boundary_digest(operator_id: str) -> str:
    identity = f"{operator_id}@1|{EXECUTION_EPOCH}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


# --- The Graph boundary ------------------------------------------------------


async def test_a_boundary_node_has_an_identity_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    # The host owns the boundary and registers neither operator, so an answer here
    # came from the boundary rule and not from a lookup someone else populated.
    for operator_id in (GRAPH_INPUT_OPERATOR_ID, GRAPH_OUTPUT_OPERATOR_ID):
        with pytest.raises(UnknownOperatorError):
            catalog.registry.node_registration(operator_id, 1)

    project = document(child_graph())
    facts = await facts_for(catalog, project)
    boundary = expanded(project, "child").instances[
        instance(expanded(project, "child"), "in")
    ]

    assert facts.implementation_digest(boundary.node) == boundary_digest(
        GRAPH_INPUT_OPERATOR_ID
    )
    assert facts.cache_policy(boundary.node) is NodeCachePolicy.EXACT


async def test_the_two_boundaries_are_distinguished_by_operator_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    facts = await facts_for(catalog, document(child_graph()))
    child = expanded(document(child_graph()), "child")
    feed = child.instances[instance(child, "in")].node
    publish = child.instances[instance(child, "out")].node

    assert facts.implementation_digest(feed) != facts.implementation_digest(publish)
    assert facts.implementation_digest(publish) == boundary_digest(
        GRAPH_OUTPUT_OPERATOR_ID
    )
    assert facts.cache_policy(publish) is NodeCachePolicy.EXACT


async def test_a_boundary_node_keeps_its_result_through_an_explicit_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    facts = await facts_for(catalog, document(boundary_and_never()))
    plain = expanded(document(boundary_and_never()), "child")
    refreshed = expanded(
        document(boundary_and_never(refresh={"in": 3, "keep": 3})), "child"
    )

    # ``EXACT`` means the refresh generation never enters the digest: what the
    # caller handed in stays valid until the caller hands in something else.
    assert (
        compute_fingerprints(plain, facts)[instance(plain, "in")]
        == (compute_fingerprints(refreshed, facts)[instance(refreshed, "in")])
    )
    # A node that does not reuse its result moves when someone refreshes it, which
    # is the only way it can be asked to run again without a document change.
    assert (
        compute_fingerprints(plain, facts)[instance(plain, "keep")]
        != (compute_fingerprints(refreshed, facts)[instance(refreshed, "keep")])
    )


def boundary_and_never(*, refresh: Mapping[str, int] | None = None) -> GraphDefinition:
    """A callee whose boundary feeds a node that never reuses its result."""
    return graph(
        "child",
        [input_node("in", "x"), never_node("keep"), output_node("out", "r")],
        [edge("in", "keep"), edge("keep", "out")],
        refresh=refresh,
    )


# --- Registered operators ----------------------------------------------------


async def test_a_registered_node_answers_from_the_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    project = document(main_graph())
    facts = await facts_for(catalog, project)
    view = expanded(project)
    reusable = view.instances[instance(view, "value")].node
    never = view.instances[instance(view, "sink")].node

    assert facts.cache_policy(reusable) is NodeCachePolicy.EXACT
    assert facts.cache_policy(never) is NodeCachePolicy.NEVER
    assert facts.implementation_digest(
        reusable
    ) == catalog.digests.implementation_digest(reusable)
    assert facts.implementation_digest(reusable) != facts.implementation_digest(never)


async def test_two_instances_of_one_node_answer_the_same_wherever_they_sit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    project = document(caller_graph("call-a", "call-b"), child_graph())
    facts = await facts_for(catalog, project)
    view = expanded(project, "main")
    first = view.instances[instance(view, "f", ("call-a",))].node
    second = view.instances[instance(view, "f", ("call-b",))].node

    assert first is second
    assert facts.implementation_digest(first) == facts.implementation_digest(second)
    assert (
        facts.cache_policy(first) == facts.cache_policy(second) == NodeCachePolicy.EXACT
    )


# --- An operator this build does not register --------------------------------


async def test_an_unregistered_operator_is_rejected_and_never_defaulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    broken = document(graph("main", [value_node("v"), ghost_node("g")]))

    # The document cannot be described, so no facts can be handed out for any of
    # it: a Run that got as far as planning would be fingerprinting a guess.
    with pytest.raises(RunRejectedError) as raised:
        await facts_for(catalog, broken)

    assert raised.value.code == "unknown_operator"
    assert GHOST_OPERATOR in str(raised.value)


async def test_an_unregistered_operator_is_rejected_at_every_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    facts = await facts_for(catalog, document(main_graph()))
    ghost = ghost_node("g")

    for ask in (facts.implementation_digest, facts.cache_policy):
        with pytest.raises(RunRejectedError) as raised:
            ask(ghost)
        assert raised.value.code == "unknown_operator"

    # Answering ``NEVER`` would be the silent wrong answer: the node would read as
    # merely non-deterministic and a Run would schedule it happily.
    with pytest.raises(RunRejectedError):
        facts.cache_policy(ghost)


async def test_a_known_operator_at_an_unknown_version_is_unknown_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    facts = await facts_for(catalog, document(main_graph()))
    stale = value_node("v").model_copy(update={"operator_version": 2})

    for ask in (facts.implementation_digest, facts.cache_policy):
        with pytest.raises(RunRejectedError) as raised:
            ask(stale)
        assert raised.value.code == "unknown_operator"


async def test_a_config_the_operator_contract_refuses_is_an_invalid_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    impossible = secret_node("f").model_copy(
        update={"config": {"credential": ["not", "a", "string"]}}
    )

    with pytest.raises(RunRejectedError) as raised:
        await facts_for(catalog, document(graph("child", [impossible])))

    assert raised.value.code == "invalid_document"
    assert "'f'" in str(raised.value)


# --- Secret revisions --------------------------------------------------------


async def test_a_node_with_no_declared_secret_costs_no_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    secrets = FakeSecretRevisionResolver()
    project = document(main_graph())

    facts = await facts_for(catalog, project, secrets)
    view = expanded(project)

    assert secrets.calls == []
    assert facts.secret_revisions(instance(view, "value")) == {}
    assert facts.secret_revisions(instance(view, "sink")) == {}


async def test_a_secret_is_read_once_per_node_under_its_declared_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    secrets = FakeSecretRevisionResolver({"api_key": "revision-9"})
    project = document(child_graph())

    facts = await facts_for(catalog, project, secrets)
    view = expanded(project, "child")

    assert secrets.calls == [
        (str(PROJECT_ID), "child", "f", "api_key", (("credential", "prod"),))
    ]
    assert facts.secret_revisions(instance(view, "f")) == {"api_key": "revision-9"}


async def test_a_secret_dependency_includes_what_the_contract_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    secrets = FakeSecretRevisionResolver()
    # The document says nothing about a credential. The operator's own contract has
    # a default, and that default is what the secret was actually read under, so
    # the effective configuration is the only honest source of dependencies.
    unconfigured = secret_node("f").model_copy(update={"config": {}})
    project = document(graph("child", [unconfigured]))

    await facts_for(catalog, project, secrets)

    assert secrets.calls == [
        (str(PROJECT_ID), "child", "f", "api_key", (("credential", "default"),))
    ]


async def test_a_graph_called_twice_runs_under_one_secret_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    secrets = FakeSecretRevisionResolver({"api_key": "shared-revision"})
    project = document(caller_graph("call-a", "call-b"), child_graph())

    facts = await facts_for(catalog, project, secrets)
    view = expanded(project, "main")
    first = facts.secret_revisions(instance(view, "f", ("call-a",)))
    second = facts.secret_revisions(instance(view, "f", ("call-b",)))

    assert first == second == {"api_key": "shared-revision"}
    # One node, one credential: the revision was not read a second time because a
    # second call path reached it.
    assert [call[:4] for call in secrets.calls] == [
        (str(PROJECT_ID), "child", "f", "api_key")
    ]


async def test_the_secret_revision_is_read_under_the_project_that_owns_the_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    secrets = FakeSecretRevisionResolver()

    await facts_for(catalog, document(child_graph()), secrets)

    assert {call[0] for call in secrets.calls} == {str(PROJECT_ID)}


async def test_an_unset_secret_is_a_revision_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    unset = FakeSecretRevisionResolver()
    unset.unset.add("api_key")
    project = document(child_graph())

    facts = await facts_for(catalog, project, unset)
    view = expanded(project, "child")

    assert facts.secret_revisions(instance(view, "f")) == {
        "api_key": UNAVAILABLE_SECRET_REVISION
    }
    # Setting it afterwards moves the fingerprint without any secret value in it.
    given = await facts_for(
        catalog, project, FakeSecretRevisionResolver({"api_key": "r-1"})
    )
    before = compute_fingerprints(view, facts)
    after = compute_fingerprints(view, given)

    assert before[instance(view, "f")] != after[instance(view, "f")]


async def test_two_calls_of_one_value_run_under_one_secret_and_one_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    secrets = FakeSecretRevisionResolver({"api_key": "revision-1"})
    same_value = document(
        caller_graph("call-a", "call-b", mark="one-value"), child_graph()
    )
    facts = await facts_for(catalog, same_value, secrets)
    view = expanded(same_value, "main")

    # The only thing that could separate the two calls is which call node was used,
    # and neither the secret revision nor the fingerprint is allowed to know it.
    assert facts.secret_revisions(
        instance(view, "f", ("call-a",))
    ) == facts.secret_revisions(instance(view, "f", ("call-b",)))
    fingerprints = compute_fingerprints(view, facts)

    assert (
        fingerprints[instance(view, "f", ("call-a",))]
        == fingerprints[instance(view, "f", ("call-b",))]
    )


async def test_the_facts_carry_no_way_to_rewrite_their_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    project = document(child_graph())
    facts = await facts_for(
        catalog, project, FakeSecretRevisionResolver({"api_key": "revision-1"})
    )
    key = instance(expanded(project, "child"), "f")

    revisions = facts.secret_revisions(key)
    with pytest.raises(TypeError):
        revisions["api_key"] = "revision-2"  # type: ignore[index]
    with pytest.raises(Exception):
        facts.secrets[(key.graph_id, key.node_id)] = {}  # type: ignore[index]

    assert facts.secret_revisions(key) == {"api_key": "revision-1"}
    with pytest.raises(Exception):
        facts.secrets = {}  # type: ignore[misc]


# --- What the document cannot ask for ---------------------------------------


async def test_a_call_node_names_a_graph_and_not_an_operator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = build_catalog(tmp_path, monkeypatch)
    project = document(caller_graph("call-a"), child_graph())

    # ``call-a`` places Graph ``child``: its ``operator_id`` is a Graph id with no
    # registration and no digest, and that must not read as ``unknown_operator``.
    await facts_for(catalog, project)


def ghost_node(node_id: str) -> GraphNode:
    return value_node(node_id).model_copy(update={"operator_id": GHOST_OPERATOR})


def _unread(snapshots: Sequence[object]) -> None:
    del snapshots


_UNUSED = (NEVER_OPERATOR, SECRET_OPERATOR, VALUE_OPERATOR, edge, _unread)
