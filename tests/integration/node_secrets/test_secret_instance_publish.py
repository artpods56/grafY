"""A secret write announces itself, and the announcement never rewrites the write.

CONTEXT.md: instance state is recomputed and diffed per Project after scheduler
transitions, accepted command batches **and secret changes**. `kernel/fingerprints.py`
folds the secret revisions a node ran under into its fingerprint, so rotating a
credential really does move what every peer reads as fresh — a write that stayed silent
would leave every other writer looking at a state the server has already invalidated.

`RunService.project_changed` is that recompute and the only emitter of `instances.changed`
on this path, which the Project room suite pins frame by frame. So what a secret route owes
is exactly that call, asked *after* its write committed: a route that asked first would
publish the state the write replaced.

The recompute cannot change the answer it follows. A peer that misses a freshness push
holds a stale view until its next read; a failure answered here would report a credential
that rotated as one that failed, and a caller who cannot tell those apart rotates it twice.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
import pytest

from grafy_core.application.project_creation import MAIN_GRAPH_ID
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint
from grafy_core.plugins import PluginRegistry
from grafy_workbench import BUILTIN_FAMILIES
from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig
from grafy_workbench.text import TEXT

from grafy_api.app_state import AppResources, get_resources
from grafy_api.node_secrets import NodeSecretService
from grafy_api.services.composition import build_workbench_components
from grafy_api.settings import Settings
from grafy_api.v1.routes.collaboration.views import websocket_browser_actor
from grafy_api.v1.routes.node_secrets.dependencies import (
    node_secret_service,
    run_service,
)
from grafy_api.v1.routes.node_secrets.models import ConfigureNodeSecretRequest

from tests.integration.node_secrets.test_node_secrets import (
    SECRET_TEST_PLUGIN,
    _encryption_key,
    _secret_document,
    _secret_project,
    _secret_service,
)
from tests.integration.runs.support import Room, install_gated_run_service
from tests.support.clients import GrafyApi
from tests.support.clients.node_secrets import NodeSecretsApi
from tests.support.clients.projects import ProjectsApi
from tests.support.identity import WORKSPACE_ID, browser_actor_override
from tests.support.workbench import workbench_dependency_overrides
from tests.testkit import (
    AppDependency,
    DependencyOverride,
    client_with_overrides,
    create_db_url,
    seed_shared_workspace,
    with_setting_values,
)

PLAINTEXT = "rotate-me-once"


class _RecordingRuns:
    """Records the recompute a secret route asks for, and what was durable when it asked.

    `seen` is read inside the call, so a route that announced before committing would
    record the state the write replaced and the ordering claim would fail.
    """

    def __init__(
        self, service: NodeSecretService, workspace_id: UUID, project_id: UUID
    ) -> None:
        self._service = service
        self._workspace_id = workspace_id
        self._project_id = project_id
        self.calls: list[tuple[UUID, UUID, tuple[bool, ...]]] = []
        self.error: Exception | None = None

    async def project_changed(self, *, workspace_id: UUID, project_id: UUID) -> None:
        state = await self._service.status(workspace_id, project_id, MAIN_GRAPH_ID)
        self.calls.append(
            (workspace_id, project_id, tuple(item.configured for item in state.secrets))
        )
        if self.error is not None:
            raise self.error


@dataclass
class Stage:
    """One booted app, its Project with one secret-declaring node, and its callers."""

    api: GrafyApi
    project_id: UUID
    runs: _RecordingRuns | None
    resources: AppResources
    room: Room | None = None

    @property
    def secrets(self) -> NodeSecretsApi:
        return self.api.workspace(WORKSPACE_ID).node_secrets

    @property
    def projects(self) -> ProjectsApi:
        return self.api.workspace(WORKSPACE_ID).projects


@contextmanager
def _stage(tmp_path: Path, name: str, *, announce: bool = True) -> Iterator[Stage]:
    """Boot the app over one seeded Project, with the recording runs installed.

    The credential key is the key the seeded secret was written under, so the app's own
    `NodeSecretService` can read it: the recompute resolves real revisions rather than
    failing for a reason this suite is not asking about.
    """

    database_url = create_db_url(tmp_path, name)
    database = create_database(database_url)
    registry = PluginRegistry()
    registry.install(SECRET_TEST_PLUGIN)
    registry.install(TEXT)
    registry.freeze()

    async def prepare() -> UUID:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        await seed_shared_workspace(database)
        return await _secret_project(database, document=_secret_document())

    project_id = asyncio.run(prepare())
    service = _secret_service(database, registry, key=_encryption_key())
    components = build_workbench_components(
        plugin_registry=registry,
        workspace=tmp_path / "announce-workbench",
        unit_of_work=SqlAlchemyUnitOfWork(create_database(database_url).sessions),
        node_secrets=service,
    )
    recorder = _RecordingRuns(service, WORKSPACE_ID, project_id) if announce else None
    overrides: dict[AppDependency, DependencyOverride] = {
        **workbench_dependency_overrides(components),
        node_secret_service: lambda: service,
    }
    if recorder is not None:
        overrides[run_service] = lambda: recorder
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                workspace=tmp_path / "workbench",
                database_url=SecretStr(database_url),
            )
        ),
        credential_encryption_key=_encryption_key(),
    )
    with client_with_overrides(settings=settings, overrides=overrides) as client:
        try:
            yield Stage(
                api=GrafyApi(client),
                project_id=project_id,
                runs=recorder,
                resources=get_resources(client.app),
            )
        finally:
            asyncio.run(database.dispose())


def _secret_request(sequence: int = 0) -> ConfigureNodeSecretRequest:
    return ConfigureNodeSecretRequest(
        value=SecretStr(PLAINTEXT), expected_head_sequence=sequence
    )


def test_configuring_a_secret_recomputes_the_project(tmp_path: Path) -> None:
    with _stage(tmp_path, "apply.sqlite3") as stage:
        configured = stage.secrets.configure_secret_ok(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", _secret_request()
        )

        assert configured.configured is True
        # One recompute of the Project the secret belongs to, asked for after the write:
        # what it could already read back was the configured secret, not the slot before.
        assert stage.runs is not None
        assert stage.runs.calls == [(WORKSPACE_ID, stage.project_id, (True,))]


def test_removing_a_secret_recomputes_the_project(tmp_path: Path) -> None:
    with _stage(tmp_path, "remove.sqlite3") as stage:
        stage.secrets.configure_secret_ok(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", _secret_request()
        )
        assert stage.runs is not None
        stage.runs.calls.clear()

        removed = stage.secrets.remove_secret(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", 0
        )

        assert removed.status_code == 204
        # A removal moves the node's fingerprint exactly as an apply does, so it is owed
        # the same recompute — and it, too, is asked for after the row is gone.
        assert stage.runs.calls == [(WORKSPACE_ID, stage.project_id, (False,))]


def test_a_failing_recompute_leaves_a_configured_secret_answered_as_configured(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with _stage(tmp_path, "apply-fails.sqlite3") as stage:
        assert stage.runs is not None
        stage.runs.error = RuntimeError("instance derivation unavailable")
        caplog.set_level("ERROR")

        configured = stage.secrets.configure_secret_ok(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", _secret_request()
        )

        assert configured.model_dump(mode="json") == {
            "node_id": "llm",
            "name": "api_key",
            "configured": True,
        }
        assert stage.secrets.list_secrets_ok(stage.project_id).secrets[0].configured
        assert _publish_failures(caplog) == 1
        # The failure is not swallowed: the write is answered and the recompute is reported.
        assert PLAINTEXT not in caplog.text


def test_a_failing_recompute_leaves_a_removal_answered_as_removed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with _stage(tmp_path, "remove-fails.sqlite3") as stage:
        stage.secrets.configure_secret_ok(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", _secret_request()
        )
        assert stage.runs is not None
        stage.runs.error = RuntimeError("instance derivation unavailable")
        caplog.set_level("ERROR")

        removed = stage.secrets.remove_secret(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", 0
        )

        assert removed.status_code == 204
        assert removed.content == b""
        assert (
            stage.secrets.list_secrets_ok(stage.project_id).secrets[0].configured
            is False
        )
        assert _publish_failures(caplog) == 1


def test_a_secret_write_never_moves_the_collaboration_head(tmp_path: Path) -> None:
    """The recompute is not a batch: secret writes advance no sequence.

    This one runs against the app's own Run service, whose registry cannot describe the
    test node, so the recompute really fails — the write is still served, and the head the
    room's writers hold their tokens against is exactly where it was. If a secret write
    moved `collaboration_sequence`, every other writer's expected-sequence token would
    break on someone else's credential rotation.
    """

    with _stage(tmp_path, "head.sqlite3", announce=False) as stage:
        before = stage.projects.get_head_ok(stage.project_id)

        configured = stage.secrets.configure_secret_ok(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", _secret_request()
        )
        mid = stage.projects.get_head_ok(stage.project_id)
        removed = stage.secrets.remove_secret(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", 0
        )

        assert configured.configured is True
        assert removed.status_code == 204
        after = stage.projects.get_head_ok(stage.project_id)
        for head in (mid, after):
            assert head.collaboration_sequence == before.collaboration_sequence == 0
            assert head.room_epoch == before.room_epoch
            assert head.checkpoint_revision == before.checkpoint_revision
            assert head.updated_at == before.updated_at


def _publish_failures(caplog: pytest.LogCaptureFixture) -> int:
    """How many times the recompute failure was reported, on any HTTP path's event name."""

    return sum(
        1
        for record in caplog.records
        if record.getMessage().startswith("project_http_instance_publish_failed")
    )


def _llm_document() -> GraphDocument:
    """One node of a Plugin release this build can really describe.

    The room tests need the Project's facts to derive, which means a registered operator
    with an implementation digest — and only a real Plugin package has a distribution in
    `uv.lock`. `llm.openai_compatible.chat_completion` is that operator, and it declares
    the `api_key` secret this suite rotates.
    """

    return GraphDocument(
        nodes=(
            GraphNode(
                kind="builtin",
                id="llm",
                operator_id="llm.openai_compatible.chat_completion",
                operator_version=1,
                config={"base_url": "https://llm.example/v1", "model": "gpt-mini"},
                position=GraphPoint(x=0, y=0),
            ),
        )
    )


@contextmanager
def _room_stage(tmp_path: Path, name: str) -> Iterator[Stage]:
    """The same app with a Run service that can derive this Project, and a joined room.

    `RunService.project_changed` is what the secret routes now call, so the service behind
    it is installed the way the Project room suite installs its own: same database, same
    hub, same fingerprint facts, and the same registry the routes advertise.
    """

    from grafy_plugin_llm import LLM

    database_url = create_db_url(tmp_path, name)
    database = create_database(database_url)
    registry = PluginRegistry()
    registry.install(LLM)
    for family in BUILTIN_FAMILIES:
        registry.install(family)
    registry.freeze()

    async def prepare() -> UUID:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        await seed_shared_workspace(database)
        return await _secret_project(database, document=_llm_document())

    project_id = asyncio.run(prepare())
    service = _secret_service(database, registry)
    components = build_workbench_components(
        plugin_registry=registry,
        workspace=tmp_path / "room-workbench",
        unit_of_work=SqlAlchemyUnitOfWork(create_database(database_url).sessions),
        node_secrets=service,
    )
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                workspace=tmp_path / "workbench",
                database_url=SecretStr(database_url),
            )
        ),
        credential_encryption_key=_encryption_key(),
    )
    with client_with_overrides(
        settings=settings,
        overrides={
            **workbench_dependency_overrides(components),
            node_secret_service: lambda: service,
            websocket_browser_actor: browser_actor_override,
        },
    ) as client:
        resources = get_resources(client.app)
        # The app serves this component graph, so build its facts from the same registry.
        resources.workbench = components
        install_gated_run_service(client.app, concurrency=1)
        try:
            with client.websocket_connect(
                f"/v1/workspaces/{WORKSPACE_ID}/projects/{project_id}/room",
                headers={"Origin": "http://testserver"},
            ) as session:
                room = Room(session)
                try:
                    room.until("room.ready", limit=6, timeout=5)
                    yield Stage(
                        api=GrafyApi(client),
                        project_id=project_id,
                        runs=None,
                        resources=resources,
                        room=room,
                    )
                finally:
                    room.close()
        finally:
            asyncio.run(database.dispose())


def test_a_secret_write_announces_the_project_on_the_room(tmp_path: Path) -> None:
    """Both directions of a credential change reach the peers that read it.

    The frame is a diff, so the sequence here is: the apply publishes the Project for the
    first time and names the node whose fingerprint it moved; the removal moves that
    fingerprint again, and the node is named again.
    """

    with _room_stage(tmp_path, "announce-room.sqlite3") as stage:
        head = stage.projects.get_head_ok(stage.project_id)
        assert head.collaboration_sequence == 0

        configured = stage.secrets.configure_secret_ok(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", _secret_request()
        )
        applied = stage.room.until("instances.changed", limit=6, timeout=5)
        assert [item["node_id"] for item in applied["changed"]] == ["llm"]

        removed = stage.secrets.remove_secret(
            stage.project_id, MAIN_GRAPH_ID, "llm", "api_key", 0
        )
        assert removed.status_code == 204
        after_removal = stage.room.until("instances.changed", limit=6, timeout=5)
        assert [item["node_id"] for item in after_removal["changed"]] == ["llm"]

        # Announcing is not editing: no sequence moved, no room reopened, and every other
        # writer's expected-sequence token still names the state it read.
        after = stage.projects.get_head_ok(stage.project_id)
        assert configured.configured is True
        assert after.collaboration_sequence == 0
        assert after.room_epoch == head.room_epoch
        assert after.checkpoint_revision == head.checkpoint_revision
