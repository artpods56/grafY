"""Agent keys are write-only, bound to their Agent, and cost `edit_project` (ADR 0021).

The double below stands where the persistence adapters stand: it holds the sealed rows in
a dictionary and honours the same transaction shape, so these assertions are about the
owner's rules — who may set a key, what comes back, what a stale seal does — and not about
SQL. The SQL itself is covered in ``tests/unit/persistence/test_agent_key_persistence.py``.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr

from grafy_core.domain.agent_keys import AGENT_KEY_AAD_VERSION, EncryptedAgentKey

from grafy_api.agents.keys import (
    AgentKeyConfigurationError,
    AgentKeyDeclarationError,
    AgentKeyService,
    AgentKeyValueError,
    AgentKeyUnavailableError,
)
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.graph_documents import CustomAgentModel, GraphAgent, GraphDocument
from grafy_core.domain.identity import (
    ActorContext,
    CapabilityDeniedError,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.kernel.project import GraphDefinition, ProjectDocument

WORKSPACE = UUID(int=501)
PROJECT = UUID(int=502)
EPOCH = UUID(int=503)
AUTHOR = UUID(int=504)
OTHER = UUID(int=505)
GRAPH_ID = "main"
AGENT_ID = "research"
OTHER_AGENT_ID = "someone-else"
SECRET = "sk-agent-very-secret-value"
ENCRYPTION_KEY = SecretStr("QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")
OTHER_ENCRYPTION_KEY = SecretStr("QkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkI=")


class KeyUnitOfWork:
    """The Agent-key and collaboration repositories, in one dictionary."""

    def __init__(self) -> None:
        self.collaboration = self
        self.agent_keys = self
        self.records: dict[tuple[UUID, UUID, str, str], object] = {}
        self.head = ProjectHead(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            room_epoch=EPOCH,
            collaboration_sequence=4,
            checkpoint_sequence=0,
            checkpoint_revision=1,
            name="Agents",
            document=ProjectDocument(
                graphs=(
                    GraphDefinition(
                        id=GRAPH_ID,
                        name="Main",
                        document=GraphDocument(
                            agents=(
                                GraphAgent(
                                    id=AGENT_ID,
                                    name="Research",
                                    model=CustomAgentModel(
                                        endpoint="https://models.example/v1",
                                        model="gpt-5-mini",
                                    ),
                                ),
                                # A second Agent on the same Graph: the row of one must
                                # not open for the other.
                                GraphAgent(id=OTHER_AGENT_ID, name="Other"),
                            )
                        ),
                    ),
                )
            ),
        )
        self.commits = 0

    async def __aenter__(self):
        self.before = deepcopy(self.records)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.records = self.before

    async def commit(self) -> None:
        self.commits += 1

    async def get_head(self, workspace_id, project_id):
        if (workspace_id, project_id) != (WORKSPACE, PROJECT):
            return None
        return self.head

    lock_head = get_head

    async def upsert(self, key) -> None:
        self.records[(key.workspace_id, key.project_id, key.graph_id, key.agent_id)] = key

    async def get(self, workspace_id, project_id, graph_id, agent_id):
        return self.records.get((workspace_id, project_id, graph_id, agent_id))

    async def list_for_graph(self, workspace_id, project_id, graph_id):
        return [
            record
            for record in self.records.values()
            if record.workspace_id == workspace_id
            and record.project_id == project_id
            and record.graph_id == graph_id
        ]

    async def remove(self, workspace_id, project_id, graph_id, agent_id) -> None:
        self.records.pop((workspace_id, project_id, graph_id, agent_id), None)


def access(role: WorkspaceRole, user_id: UUID = AUTHOR) -> WorkspaceAccess:
    return WorkspaceAccess(
        actor=ActorContext(user_id=user_id),
        workspace_id=WORKSPACE,
        membership=WorkspaceMembership(
            workspace_id=WORKSPACE, user_id=user_id, role=role
        ),
    )


def service(
    unit_of_work: KeyUnitOfWork, encryption_key: SecretStr | None = ENCRYPTION_KEY
) -> AgentKeyService:
    return AgentKeyService(
        unit_of_work_factory=lambda: unit_of_work, encryption_key=encryption_key
    )


async def set_and_read(
    unit_of_work: KeyUnitOfWork, *, role: WorkspaceRole = WorkspaceRole.EDITOR
) -> None:
    await service(unit_of_work).set_key(
        access=access(role),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        value=SecretStr(SECRET),
    )


def test_the_sealed_record_is_only_material_and_coordinates() -> None:
    """The row cannot be built into something that reads as a credential.

    An empty coordinate, a truncated nonce, another build's binding layout, or no
    ciphertext each make the record unusable, so it is refused where it is written rather
    than at the first send.
    """

    def record(**overrides: object) -> EncryptedAgentKey:
        values: dict[str, object] = {
            "workspace_id": WORKSPACE,
            "project_id": PROJECT,
            "graph_id": GRAPH_ID,
            "agent_id": AGENT_ID,
            "key_id": "0123456789abcdef",
            "aad_version": AGENT_KEY_AAD_VERSION,
            "nonce": b"0123456789ab",
            "ciphertext": b"sealed",
            "set_by_user_id": AUTHOR,
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
        values.update(overrides)
        return EncryptedAgentKey(**values)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="agent_id must not be empty"):
        record(agent_id="   ")
    with pytest.raises(ValueError, match="nonce must be exactly 12 bytes"):
        record(nonce=b"short")
    with pytest.raises(ValueError, match="ciphertext must not be empty"):
        record(ciphertext=b"")
    with pytest.raises(ValueError, match="AAD version"):
        record(aad_version=3)
    with pytest.raises(ValueError, match="timestamps must be timezone-aware"):
        record(created_at=datetime(2026, 9, 1))

    assert SECRET not in repr(record())
    assert "nonce=<redacted>" in repr(record())


@pytest.mark.asyncio
async def test_an_editor_without_manage_secrets_can_give_an_agent_its_key() -> None:
    """The ADR's rule, tested as a rule: an Agent key follows the canvas permission.

    A node secret needs `manage_secrets`; an Agent's key is part of configuring a canvas
    object, so `edit_project` is the whole requirement — and an editor, who cannot touch a
    node secret, is exactly the person ADR 0021 says may set this one.
    """

    editor = access(WorkspaceRole.EDITOR)
    assert editor.membership.grants(WorkspaceCapability.EDIT_PROJECT)
    assert not editor.membership.grants(WorkspaceCapability.MANAGE_SECRETS)

    unit_of_work = KeyUnitOfWork()
    await set_and_read(unit_of_work)
    assert unit_of_work.commits == 1

    resolved = await service(unit_of_work).resolve_key(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
    )
    assert resolved.get_secret_value() == SECRET


@pytest.mark.asyncio
async def test_a_viewer_cannot_set_or_clear_an_agents_key() -> None:
    unit_of_work = KeyUnitOfWork()

    with pytest.raises(CapabilityDeniedError) as denied:
        await set_and_read(unit_of_work, role=WorkspaceRole.VIEWER)
    assert denied.value.capability == "edit_project"
    assert unit_of_work.records == {}
    assert unit_of_work.commits == 0

    with pytest.raises(CapabilityDeniedError):
        await service(unit_of_work).clear_key(
            access=access(WorkspaceRole.VIEWER),
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
        )


@pytest.mark.asyncio
async def test_the_configuration_surface_never_shows_the_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """State, repr, the stored record and the log all say a key exists, none says what it is."""

    unit_of_work = KeyUnitOfWork()
    owner = service(unit_of_work)
    state = await owner.set_key(
        access=access(WorkspaceRole.OWNER),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        value=SecretStr(SECRET),
    )
    stored = next(iter(unit_of_work.records.values()))

    assert state.configured is True
    for surface in (repr(state), str(state), repr(stored), str(stored)):
        assert SECRET not in surface
    assert SECRET not in caplog.text
    assert "nonce=<redacted>" in repr(stored)
    assert unit_of_work.commits == 1


@pytest.mark.asyncio
async def test_state_reports_what_this_server_can_actually_use() -> None:
    """A row sealed under another deployment key is not a configured Agent."""

    unit_of_work = KeyUnitOfWork()
    await set_and_read(unit_of_work)
    assert (
        await service(unit_of_work).state(
            access=access(WorkspaceRole.VIEWER),
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
        )
    ).configured is True

    rotated = service(unit_of_work, encryption_key=OTHER_ENCRYPTION_KEY)
    state = await rotated.state(
        access=access(WorkspaceRole.VIEWER),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
    )
    assert state.configured is False
    with pytest.raises(AgentKeyUnavailableError, match="cannot be decrypted"):
        await rotated.resolve_key(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
        )


@pytest.mark.asyncio
async def test_clearing_an_agents_key_leaves_the_deployment_default_as_the_only_way_to_answer() -> None:
    unit_of_work = KeyUnitOfWork()
    owner = service(unit_of_work)
    await set_and_read(unit_of_work)

    cleared = await owner.clear_key(
        access=access(WorkspaceRole.EDITOR),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
    )
    assert cleared.configured is False
    assert unit_of_work.records == {}
    with pytest.raises(AgentKeyUnavailableError, match="no configured model key"):
        await owner.resolve_key(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
        )


@pytest.mark.asyncio
async def test_a_seal_copied_beside_another_agent_does_not_open() -> None:
    """The binding is the Agent's coordinates, so a copied row is a foreign row."""

    unit_of_work = KeyUnitOfWork()
    await set_and_read(unit_of_work)
    (key, record), = unit_of_work.records.items()
    unit_of_work.records[(*key[:3], OTHER_AGENT_ID)] = replace(
        record, agent_id=OTHER_AGENT_ID
    )

    with pytest.raises(AgentKeyUnavailableError, match="cannot be decrypted"):
        await service(unit_of_work).resolve_key(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=OTHER_AGENT_ID,
        )


@pytest.mark.asyncio
async def test_a_key_belongs_to_an_agent_that_is_on_the_canvas() -> None:
    unit_of_work = KeyUnitOfWork()
    owner = service(unit_of_work)

    with pytest.raises(AgentKeyDeclarationError, match="is not on graph"):
        await owner.set_key(
            access=access(WorkspaceRole.OWNER),
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id="removed-agent",
            value=SecretStr(SECRET),
        )
    assert unit_of_work.records == {}
    assert unit_of_work.commits == 0

    with pytest.raises(NotFoundError, match="Graph not found"):
        await owner.set_key(
            access=access(WorkspaceRole.OWNER),
            project_id=PROJECT,
            graph_id="other-graph",
            agent_id=AGENT_ID,
            value=SecretStr(SECRET),
        )

    with pytest.raises(NotFoundError, match="Project not found"):
        await owner.state(
            access=access(WorkspaceRole.OWNER),
            project_id=UUID(int=509),
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
        )


@pytest.mark.parametrize(
    ("value", "message"),
    [("", "must not be empty"), ("   ", "must not be empty"), ("x" * 65_537, "65536")],
)
@pytest.mark.asyncio
async def test_only_a_credential_worth_sealing_is_sealed(
    value: str, message: str
) -> None:
    unit_of_work = KeyUnitOfWork()

    with pytest.raises(AgentKeyValueError, match=message):
        await service(unit_of_work).set_key(
            access=access(WorkspaceRole.OWNER),
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
            value=SecretStr(value),
        )
    assert unit_of_work.records == {}


@pytest.mark.asyncio
async def test_without_a_deployment_key_the_owner_says_so_instead_of_failing_later() -> None:
    unit_of_work = KeyUnitOfWork()
    unconfigured = service(unit_of_work, encryption_key=None)

    with pytest.raises(AgentKeyConfigurationError, match="GRAFY_CREDENTIAL_ENCRYPTION_KEY"):
        await unconfigured.set_key(
            access=access(WorkspaceRole.OWNER),
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
            value=SecretStr(SECRET),
        )

    state = await unconfigured.state(
        access=access(WorkspaceRole.VIEWER),
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
    )
    assert state.configured is False
