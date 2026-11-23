"""Starter Projects: sample seeding, Document OCR wiring, and credential binding."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from tests.unit.application.project_fakes import (
    IdentityDirectory,
    ProjectStore,
    ProjectUnitOfWorkFactory,
    new_member,
)

from grafy_api.catalog_packs import CatalogPolicy
from grafy_api.library.service import LibraryService
from grafy_api.project_contracts import StarterId
from grafy_api.services.composition import build_workbench_components
from grafy_api.services.families import build_application_registry
from grafy_api.starter_samples import sample_bytes, sample_sha256
from grafy_api.starters import (
    ENGINE_EDGE_ID,
    ENGINE_NODE_ID,
    MARKDOWN_EDGE_ID,
    OCR_NODE_ID,
    ORIGIN_ID,
    RESULT_LINK_ID,
    RESULT_VIEWER_ID,
    SAMPLE_VIEWER_ID,
    TABLE_NODE_ID,
    StarterService,
    StarterUnavailableError,
)
from grafy_core.application.collaboration import CollaborationService
from grafy_core.artifacts import ArtifactRef
from grafy_core.canonical_conversions import PNG_FILE_TO_RASTER
from grafy_core.domain.credentials import SharedCredentialBindingMode
from grafy_core.domain.errors import CapabilityDeniedError
from grafy_core.domain.identity import ActorContext, Workspace, WorkspaceRole
from grafy_core.egress import EgressPolicy
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.identity import IdentityUnitOfWorkPort
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_shared.config.catalog import CatalogOverrides

HMAC_KEY = b"test-project-command-hmac-key"
SAMPLE_SHA256 = "d9e0a68668a4c3fabf016b15ef39c8d3705d07f2641cbe1dc68628f81774ba3c"


@dataclass(frozen=True, slots=True)
class _Credential:
    id: UUID
    provider_kind: str


class _Credentials:
    def __init__(self, rows: list[_Credential]) -> None:
        self.rows = rows

    async def list_shared(
        self, workspace_id: UUID, provider_kind: str | None = None
    ) -> list[_Credential]:
        del workspace_id
        if provider_kind is None:
            return list(self.rows)
        return [row for row in self.rows if row.provider_kind == provider_kind]


class _Bindings:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def set_shared_binding(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        mode: SharedCredentialBindingMode,
        credential_id: UUID | None,
        actor_user_id: UUID,
        expected_head_sequence: int,
    ) -> None:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "name": name,
                "mode": mode,
                "credential_id": credential_id,
                "actor_user_id": actor_user_id,
                "expected_head_sequence": expected_head_sequence,
            }
        )


class _Packs:
    def __init__(self, slugs: frozenset[str]) -> None:
        self._slugs = slugs

    async def list_slugs(self, workspace_id: UUID) -> frozenset[str]:
        del workspace_id
        return self._slugs


class _PackUow:
    def __init__(self, slugs: frozenset[str]) -> None:
        self.workspace_packs = _Packs(slugs)

    async def __aenter__(self) -> "_PackUow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@dataclass
class _World:
    uow: InMemoryUnitOfWork
    service: StarterService
    library: LibraryService
    collaboration: CollaborationService
    store: ProjectStore
    bindings: _Bindings
    workspace: Workspace
    actor: ActorContext


@pytest.fixture(scope="module")
def registry() -> PluginRegistry:
    return build_application_registry()


def _policy(
    registry: PluginRegistry, *, operators: dict[str, bool] | None = None
) -> CatalogPolicy:
    return CatalogPolicy(
        registry,
        CatalogOverrides(operators=operators or {}),
    )


def _world(
    tmp_path: Path,
    registry: PluginRegistry,
    *,
    role: WorkspaceRole = WorkspaceRole.EDITOR,
    slugs: frozenset[str] | None = None,
    credentials: list[_Credential] | None = None,
    operators: dict[str, bool] | None = None,
    packs: dict[str, bool] | None = None,
) -> _World:
    directory = IdentityDirectory()
    store = ProjectStore(directory)
    workspace, user = new_member(
        directory, display_name="Atlas", slug="atlas", role=role
    )
    store.seed_location(workspace)
    uow = InMemoryUnitOfWork()
    components = build_workbench_components(
        plugin_registry=registry,
        workspace=tmp_path,
        unit_of_work=uow,
        egress_policy=EgressPolicy(),
    )
    policy = CatalogPolicy(
        registry,
        CatalogOverrides(operators=operators or {}, packs=packs or {}),
    )
    subscribed = slugs if slugs is not None else frozenset({"document_ocr"})
    bindings = _Bindings()
    collaboration = CollaborationService(
        ProjectUnitOfWorkFactory(store),
        command_hmac_key=HMAC_KEY,
        command_hmac_key_version=3,
    )
    service = StarterService(
        uploads=components.uploads,
        library=components.library,
        collaboration=collaboration,
        credentials=_Credentials(credentials or []),
        node_secrets=bindings,
        registry=registry,
        policy=policy,
        identity_uow_factory=cast(
            Callable[[], IdentityUnitOfWorkPort], lambda: _PackUow(subscribed)
        ),
    )
    return _World(
        uow=uow,
        service=service,
        library=components.library,
        collaboration=collaboration,
        store=store,
        bindings=bindings,
        workspace=workspace,
        actor=ActorContext(user_id=user.id, credential_reference="session:test"),
    )


def _graph(world: _World, project_id: UUID):
    head = world.store.head_for(world.workspace.id, project_id)
    return head.document.get_graph("main").document


def test_bundled_sample_is_a_small_png() -> None:
    payload = sample_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) < 200_000
    assert sample_sha256() == SAMPLE_SHA256


async def test_sample_is_seeded_once_at_the_library_root(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    world = _world(tmp_path, registry)
    first = await world.service.seed_sample(
        workspace_id=world.workspace.id, created_by_user_id=world.actor.user_id
    )
    assert first.folder_id is None
    assert first.name == "PNG image"
    assert first.provenance.original_filename == "sample-historical-table.png"
    assert first.artifact.artifact_type == "file.png"
    assert first.artifact.schema_version == 1
    assert first.artifact.sha256 == SAMPLE_SHA256

    folder_id = uuid4()
    async with world.uow as uow:
        await uow.library_folders.place(
            world.workspace.id, [first.artifact.artifact_id], folder_id
        )
        await uow.commit()

    second = await world.service.seed_sample(
        workspace_id=world.workspace.id, created_by_user_id=world.actor.user_id
    )
    assert second.artifact.artifact_id == first.artifact.artifact_id
    assert second.folder_id == folder_id
    listed = await world.library.list_items(world.workspace.id)
    assert len(listed) == 1


async def test_transcribe_starter_wires_one_shared_credential(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    credential = _Credential(id=uuid4(), provider_kind="mistral")
    world = _world(tmp_path, registry, credentials=[credential])
    project = await world.service.create_starter(
        actor=world.actor,
        workspace_id=world.workspace.id,
        starter_id=StarterId.TRANSCRIBE_PAGE,
    )
    assert project.name == "Transcribe a scanned page"
    document = _graph(world, project.id)
    assert [node.operator_id for node in document.nodes] == [
        "ocr.read_document",
        "mistral.ocr.provider",
    ]
    assert document.nodes[1].id == ENGINE_NODE_ID
    assert [edge.id for edge in document.edges] == [ENGINE_EDGE_ID]
    assert document.edges[0].from_port == "engine"
    assert document.edges[0].to_port == "engine"
    origin = document.origins[0]
    assert origin.id == ORIGIN_ID
    assert origin.to_port == "document"
    assert origin.source_card_ids == (SAMPLE_VIEWER_ID,)
    assert origin.conversion_path[0].id == PNG_FILE_TO_RASTER.id
    assert isinstance(origin.value, ArtifactRef)
    assert origin.value.content_hash == SAMPLE_SHA256
    viewers = {viewer.id: viewer for viewer in document.presentation.viewers}
    assert viewers[SAMPLE_VIEWER_ID].artifact_ref == origin.value
    assert viewers[RESULT_VIEWER_ID].artifact_ref is None
    link = document.presentation.links[0]
    assert link.id == RESULT_LINK_ID
    assert link.source_node_id == OCR_NODE_ID
    assert link.source_port_name == "markdown"
    assert world.bindings.calls == [
        {
            "workspace_id": world.workspace.id,
            "project_id": project.id,
            "graph_id": "main",
            "node_id": ENGINE_NODE_ID,
            "name": "api_key",
            "mode": SharedCredentialBindingMode.CREDENTIAL,
            "credential_id": credential.id,
            "actor_user_id": world.actor.user_id,
            "expected_head_sequence": 0,
        }
    ]


async def test_extract_starter_follows_the_table(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    world = _world(tmp_path, registry, credentials=[])
    project = await world.service.create_starter(
        actor=world.actor,
        workspace_id=world.workspace.id,
        starter_id=StarterId.EXTRACT_TABLE,
    )
    document = _graph(world, project.id)
    assert project.name == "Extract a table from a scanned register"
    assert [node.id for node in document.nodes] == [
        OCR_NODE_ID,
        ENGINE_NODE_ID,
        TABLE_NODE_ID,
    ]
    assert document.nodes[2].operator_id == "table.extract_from_markdown"
    markdown = next(edge for edge in document.edges if edge.id == MARKDOWN_EDGE_ID)
    assert markdown.from_port == "markdown"
    assert markdown.to_port == "markdown"
    link = document.presentation.links[0]
    assert link.source_node_id == TABLE_NODE_ID
    assert link.source_port_name == "table"
    assert world.bindings.calls == []


async def test_ambiguous_shared_credential_leaves_the_key_prompt(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    world = _world(
        tmp_path,
        registry,
        credentials=[
            _Credential(id=uuid4(), provider_kind="mistral"),
            _Credential(id=uuid4(), provider_kind="mistral"),
        ],
    )
    project = await world.service.create_starter(
        actor=world.actor,
        workspace_id=world.workspace.id,
        starter_id=StarterId.TRANSCRIBE_PAGE,
    )
    document = _graph(world, project.id)
    assert document.nodes[1].operator_id == "mistral.ocr.provider"
    assert world.bindings.calls == []


async def test_no_visible_provider_leaves_the_engine_open(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    policy = _policy(registry)
    visible = [
        registration.node_class.operator_id
        for registration in registry.nodes
        if registration.role == "provider"
        and policy.is_visible(registration, frozenset({"document_ocr", "essentials"}))
        and any(
            port.service_contracts
            and any(key.id == "ocr.document" for key in port.service_contracts)
            for port in registration.node_class.output_contract.ports.values()
        )
    ]
    assert "mistral.ocr.provider" in visible
    world = _world(
        tmp_path,
        registry,
        operators={operator_id: False for operator_id in visible},
    )
    project = await world.service.create_starter(
        actor=world.actor,
        workspace_id=world.workspace.id,
        starter_id=StarterId.TRANSCRIBE_PAGE,
    )
    document = _graph(world, project.id)
    assert [node.operator_id for node in document.nodes] == ["ocr.read_document"]
    assert document.edges == ()
    assert world.bindings.calls == []


async def test_document_ocr_must_be_subscribed_and_enabled(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    unsubscribed = _world(tmp_path, registry, slugs=frozenset())
    with pytest.raises(StarterUnavailableError, match="Document OCR"):
        await unsubscribed.service.create_starter(
            actor=unsubscribed.actor,
            workspace_id=unsubscribed.workspace.id,
            starter_id=StarterId.TRANSCRIBE_PAGE,
        )
    assert await unsubscribed.library.list_items(unsubscribed.workspace.id) == []

    disabled = _world(tmp_path / "disabled", registry, packs={"document_ocr": False})
    with pytest.raises(StarterUnavailableError, match="Document OCR"):
        await disabled.service.create_starter(
            actor=disabled.actor,
            workspace_id=disabled.workspace.id,
            starter_id=StarterId.TRANSCRIBE_PAGE,
        )


async def test_viewer_cannot_open_a_starter(
    tmp_path: Path, registry: PluginRegistry
) -> None:
    world = _world(tmp_path, registry, role=WorkspaceRole.VIEWER)
    with pytest.raises(CapabilityDeniedError):
        await world.service.create_starter(
            actor=world.actor,
            workspace_id=world.workspace.id,
            starter_id=StarterId.TRANSCRIBE_PAGE,
        )
