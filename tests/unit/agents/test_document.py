import pytest
from pydantic import ValidationError

from grafy_core.domain.collaboration import (
    AddAgentCommand,
    ConfigureAgentCommand,
    RemoveAgentCommand,
    apply_graph_command,
    sanitize_document_for_cross_workspace_copy,
)
from uuid import uuid4

from grafy_core.domain.collaboration import RemoveNodesCommand
from grafy_core.domain.graph_documents import (
    AgentContextLink,
    AgentToolLink,
    CustomAgentModel,
    GraphAgent,
    GraphDocument,
)
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.fingerprints import compute_fingerprints
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from tests.unit.kernel.builders import FakeFacts, make_node


def test_agent_does_not_change_expansion_or_fingerprints():
    original = GraphDocument(nodes=(make_node("source"),))
    changed = apply_graph_command(
        document=original,
        command=AddAgentCommand(agent=GraphAgent(id="a", name="Research")),
    )

    def expand(document):
        return expand_graph(
            ProjectDocument(
                graphs=(GraphDefinition(id="g", name="Main", document=document),)
            ),
            "g",
            project_id="p",
        )

    before, after = expand(original), expand(changed)
    assert before == after
    assert compute_fingerprints(before, FakeFacts()) == compute_fingerprints(
        after, FakeFacts()
    )
    assert changed.with_topology(nodes=()).agents == changed.agents
    assert sanitize_document_for_cross_workspace_copy(changed).agents == changed.agents


def test_agent_commands_and_roundtrip():
    agent = GraphAgent(id="a", name="Research")
    document = apply_graph_command(
        document=GraphDocument(), command=AddAgentCommand(agent=agent)
    )
    assert GraphDocument.model_validate_json(document.model_dump_json()).agents == (
        agent,
    )
    updated = agent.model_copy(update={"instructions": "Use primary sources"})
    document = apply_graph_command(
        document=document, command=ConfigureAgentCommand(agent=updated)
    )
    assert document.agents == (updated,)
    document = apply_graph_command(
        document=document, command=RemoveAgentCommand(agent_id="a")
    )
    assert document.agents == ()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1/v1",
        "http://localhost/v1",
        "https://user:pass@example.com",
        "https://example.com?key=secret",
    ],
)
def test_custom_model_rejects_unsafe_endpoints(endpoint):
    with pytest.raises(ValidationError):
        CustomAgentModel(endpoint=endpoint, model="chat")


def test_agent_ids_are_unique():
    agent = GraphAgent(id="a", name="Research")
    with pytest.raises(ValidationError):
        GraphDocument(agents=(agent, agent))


def test_batch_rejects_duplicate_agent_without_mutating_original():
    from grafy_core.domain.collaboration import InGraphCommand, apply_project_commands
    from grafy_core.domain.errors import CollaborationCommandRejectedError

    original = ProjectDocument(
        graphs=(GraphDefinition(id="g", name="Main", document=GraphDocument()),)
    )
    add = InGraphCommand(
        graph_id="g", command=AddAgentCommand(agent=GraphAgent(id="a", name="Research"))
    )
    with pytest.raises(CollaborationCommandRejectedError):
        apply_project_commands(name="Project", document=original, commands=(add, add))
    assert original.graphs[0].document.agents == ()


@pytest.mark.parametrize(
    "command",
    [
        ConfigureAgentCommand(agent=GraphAgent(id="missing", name="Research")),
        RemoveAgentCommand(agent_id="missing"),
    ],
)
def test_missing_agent_is_rejected(command):
    from grafy_core.domain.errors import CollaborationCommandRejectedError

    with pytest.raises(CollaborationCommandRejectedError):
        apply_graph_command(document=GraphDocument(), command=command)


# --- What is connected to an Agent (ADR 0021) --------------------------------


def _tool(tool_id="t1", node_id="reader", name="read_text", **fields):
    return AgentToolLink(id=tool_id, node_id=node_id, name=name, **fields)


def test_context_links_name_exactly_the_fields_their_kind_needs():
    AgentContextLink(id="c1", kind="node_output", node_id="reader", port="text")
    AgentContextLink(id="c2", kind="card", card_id="card-1")
    AgentContextLink(id="c3", kind="library_item", library_item_id=uuid4())
    for incomplete in (
        {"kind": "node_output", "node_id": "reader"},
        {"kind": "card"},
        {"kind": "library_item"},
    ):
        with pytest.raises(ValidationError):
            AgentContextLink(id="c", **incomplete)
    with pytest.raises(ValidationError):
        AgentContextLink(id="c", kind="card", card_id="card-1", node_id="reader")


@pytest.mark.parametrize("name", ["", "Read Text", "9lives", "a" * 49, "read-text"])
def test_a_tool_name_is_a_short_lower_case_identifier(name):
    with pytest.raises(ValidationError):
        _tool(name=name)


def test_a_tool_names_each_port_once():
    with pytest.raises(ValidationError):
        _tool(filled_ports=("query", "query"))
    with pytest.raises(ValidationError):
        _tool(returned_ports=("text", "text"))


def test_an_agents_links_and_tool_names_are_unique():
    with pytest.raises(ValidationError):
        GraphAgent(id="a", name="A", tools=(_tool("t1"), _tool("t1", name="other")))
    with pytest.raises(ValidationError):
        GraphAgent(id="a", name="A", tools=(_tool("t1"), _tool("t2")))
    with pytest.raises(ValidationError):
        GraphAgent(
            id="a",
            name="A",
            tools=(_tool("same"),),
            context=(AgentContextLink(id="same", kind="card", card_id="x"),),
        )


def test_a_document_refuses_a_link_to_a_node_it_does_not_hold():
    tooled = GraphAgent(id="a", name="A", tools=(_tool(),))
    with pytest.raises(ValidationError):
        GraphDocument(agents=(tooled,), nodes=(make_node("other"),))
    GraphDocument(agents=(tooled,), nodes=(make_node("reader"),))
    fed = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(id="c", kind="node_output", node_id="ghost", port="text"),
        ),
    )
    with pytest.raises(ValidationError):
        GraphDocument(agents=(fed,), nodes=(make_node("reader"),))


def test_a_card_or_library_link_may_dangle():
    dangling = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(id="c1", kind="card", card_id="gone"),
            AgentContextLink(id="c2", kind="library_item", library_item_id=uuid4()),
        ),
    )
    assert GraphDocument(agents=(dangling,)).agents == (dangling,)


def test_removing_a_node_removes_the_links_to_it_and_no_others():
    agent = GraphAgent(
        id="a",
        name="A",
        tools=(_tool("t1", "reader"), _tool("t2", "writer", name="write_text")),
        context=(
            AgentContextLink(
                id="c1", kind="node_output", node_id="reader", port="text"
            ),
            AgentContextLink(id="c2", kind="card", card_id="card-1"),
        ),
    )
    document = GraphDocument(
        agents=(agent,), nodes=(make_node("reader"), make_node("writer"))
    )

    after = apply_graph_command(
        document=document, command=RemoveNodesCommand(node_ids=("reader",))
    )

    (kept,) = after.agents
    assert [tool.id for tool in kept.tools] == ["t2"]
    assert [link.id for link in kept.context] == ["c2"]


def test_a_cross_workspace_copy_drops_library_links_and_keeps_the_rest():
    agent = GraphAgent(
        id="a",
        name="A",
        context=(
            AgentContextLink(id="c1", kind="library_item", library_item_id=uuid4()),
            AgentContextLink(id="c2", kind="card", card_id="card-1"),
        ),
    )

    copied = sanitize_document_for_cross_workspace_copy(GraphDocument(agents=(agent,)))

    assert [link.id for link in copied.agents[0].context] == ["c2"]


def test_links_survive_a_json_round_trip():
    agent = GraphAgent(
        id="a",
        name="A",
        tools=(_tool(filled_ports=("query",), returned_ports=("text",)),),
    )
    document = GraphDocument(agents=(agent,), nodes=(make_node("reader"),))

    assert GraphDocument.model_validate_json(document.model_dump_json()) == document
