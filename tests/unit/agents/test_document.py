import pytest
from pydantic import ValidationError

from grafy_core.domain.collaboration import (
    AddAgentCommand,
    ConfigureAgentCommand,
    RemoveAgentCommand,
    apply_graph_command,
    sanitize_document_for_cross_workspace_copy,
)
from grafy_core.domain.graph_documents import (
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

    original = ProjectDocument(graphs=(GraphDefinition(id="g", name="Main", document=GraphDocument()),))
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
