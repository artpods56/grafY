import asyncio
from pathlib import Path
import shutil
from uuid import UUID

import pytest
from typing_extensions import override
from sqlalchemy import func, select

from grafy_persistence import schema

from grafy_api.plugins.publication.authoring import (
    PluginAuthoringConflictError,
    PluginAuthoringService,
)
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.workflow import (
    PluginPublicationConflictError,
    PluginPublicationWorkflow,
)
from grafy_api.plugins.publication.source import (
    PluginDirectoryPublisher,
    VerifiedPluginCandidate,
)
from grafy_api.system_plugin_inventory import (
    CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
    load_system_plugin_inventory,
)
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.errors import UserDisabledError
from grafy_core.domain.plugin_releases import (
    PluginRuntimeArtifact,
)
from grafy_core.runtime.plugin_loader import WORKSPACE_PLUGIN_LOADER_TARGET
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import (
    TEST_USER_ID,
    WORKSPACE_ID as SEEDED_WORKSPACE_ID,
    create_schema,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ID = SEEDED_WORKSPACE_ID
ACTOR_ID = TEST_USER_ID


class RecordingImageBuilder(PluginOciImageBuilder):
    def __init__(self) -> None:
        self.build_count = 0
        self.loader_targets: list[str] = []

    @override
    async def build_and_store(
        self,
        *,
        candidate: VerifiedPluginCandidate,
    ) -> PluginRuntimeArtifact:
        self.build_count += 1
        self.loader_targets.append(candidate.loader_target)
        return PluginRuntimeArtifact(
            object_key=(
                f"plugin-releases/{candidate.catalog.slug}/runtime/"
                f"{candidate.source_digest}.oci.tar"
            ),
            archive_digest=candidate.source_digest,
            manifest_digest="a" * 64,
            config_digest="b" * 64,
        )


def test_agent_authoring_scaffolds_reviews_fences_and_uses_shared_publisher(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'authoring.sqlite3'}"
    asyncio.run(create_schema(database_url))
    database = create_database(database_url)
    storage = LocalFileObjectStore(tmp_path / "objects")
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        storage,
        bucket="authoring-test",
    )
    image_builder = RecordingImageBuilder()
    plugin_root = tmp_path / "plugins"
    publication = PluginPublicationWorkflow(
        PluginDirectoryPublisher(
            (plugin_root,),
            runtime_profile="python-uv",
        ),
        image_builder,
        releases,
        load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH),
    )
    authoring = PluginAuthoringService(
        authoring_root=plugin_root,
        allowed_roots=(plugin_root,),
        sdk_project=REPOSITORY_ROOT / "libs" / "core",
        publication=publication,
        releases=releases,
        storage=storage,
        bucket="authoring-test",
    )

    with pytest.raises(UserDisabledError, match="is disabled"):
        asyncio.run(
            publication.publish(
                workspace_id=WORKSPACE_ID,
                directory=plugin_root / "missing",
                expected_slug="generated-notes",
                published_by_user_id=UUID(int=999),
            )
        )
    assert image_builder.build_count == 0

    reservation = authoring.scaffold(
        workspace_id=WORKSPACE_ID,
        slug="generated-notes",
        operator_slug="create",
        title="Generated notes",
        actor_user_id=ACTOR_ID,
    )
    project = reservation.project_directory
    assert project == plugin_root / str(WORKSPACE_ID) / "generated-notes"
    assert (project / "pyproject.toml").is_file()
    assert (project / "uv.lock").is_file()
    assert (project / "src" / "grafy_plugin" / "__init__.py").is_file()
    assert (project / "tests" / "test_plugin.py").is_file()
    assert list((project / "wheels").glob("grafy_core-*.whl"))
    assert "generated.node" not in (
        project / "src" / "grafy_plugin" / "nodes.py"
    ).read_text(encoding="utf-8")

    other_workspace_id = UUID(int=2)
    other_project = plugin_root / str(other_workspace_id) / "generated-notes"
    shutil.copytree(
        project,
        other_project,
        ignore=shutil.ignore_patterns(".grafy", ".venv"),
    )
    other_reservation = authoring.reserve(
        workspace_id=other_workspace_id,
        slug="generated-notes",
        actor_user_id=ACTOR_ID,
    )
    assert other_reservation.project_directory == other_project
    assert other_reservation.project_directory != project
    authoring.release(
        workspace_id=other_workspace_id,
        slug="generated-notes",
        actor_user_id=ACTOR_ID,
        session_id=other_reservation.session_id,
    )

    with pytest.raises(PluginAuthoringConflictError, match="active authoring"):
        authoring.reserve(
            workspace_id=WORKSPACE_ID,
            slug="generated-notes",
            actor_user_id=ACTOR_ID,
        )

    first_review = asyncio.run(
        authoring.review(
            workspace_id=WORKSPACE_ID,
            slug="generated-notes",
            actor_user_id=ACTOR_ID,
            session_id=reservation.session_id,
        )
    )
    assert first_review.base_revision is None
    assert first_review.changes
    assert {change.kind for change in first_review.changes} == {"added"}
    assert "working-copy/src/grafy_plugin/nodes.py" in first_review.unified_diff
    assert first_review.node_contract_changed is True
    assert first_review.artifact_contract_changed is True
    assert first_review.capabilities_changed is True
    assert first_review.runtime_profile_changed is True

    nodes = project / "src" / "grafy_plugin" / "nodes.py"
    nodes.write_text(
        nodes.read_text(encoding="utf-8") + "\n# changed after review\n",
        encoding="utf-8",
    )
    with pytest.raises(
        PluginPublicationConflictError,
        match="changed after review",
    ):
        asyncio.run(
            authoring.publish(
                workspace_id=WORKSPACE_ID,
                slug="generated-notes",
                actor_user_id=ACTOR_ID,
                session_id=reservation.session_id,
            )
        )
    assert asyncio.run(releases.list_current(WORKSPACE_ID)) == []

    second_review = asyncio.run(
        authoring.review(
            workspace_id=WORKSPACE_ID,
            slug="generated-notes",
            actor_user_id=ACTOR_ID,
            session_id=reservation.session_id,
        )
    )
    agent_release = asyncio.run(
        authoring.publish(
            workspace_id=WORKSPACE_ID,
            slug="generated-notes",
            actor_user_id=ACTOR_ID,
            session_id=reservation.session_id,
        )
    )
    assert agent_release.release.revision == 1
    assert agent_release.release.source_digest == second_review.source_digest
    assert agent_release.release.published_by_user_id == ACTOR_ID
    assert not (project / ".grafy" / "authoring.json").exists()

    human_release = asyncio.run(
        publication.publish(
            workspace_id=WORKSPACE_ID,
            directory=project,
            expected_slug="generated-notes",
            published_by_user_id=ACTOR_ID,
        )
    )
    assert human_release == agent_release
    assert image_builder.build_count == 1
    assert image_builder.loader_targets == [
        WORKSPACE_PLUGIN_LOADER_TARGET,
    ]
    asyncio.run(database.dispose())


class PausingImageBuilder(RecordingImageBuilder):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.resume = asyncio.Event()

    @override
    async def build_and_store(
        self,
        *,
        candidate: VerifiedPluginCandidate,
    ) -> PluginRuntimeArtifact:
        self.started.set()
        await self.resume.wait()
        return await super().build_and_store(candidate=candidate)


@pytest.mark.parametrize("base_revision", [0, 1])
async def test_reviewed_publication_rejects_release_published_during_image_build(
    tmp_path: Path,
    base_revision: int,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'publication-race.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="publication-race",
    )
    image_builder = PausingImageBuilder()
    examples = REPOSITORY_ROOT / "examples"
    publication = PluginPublicationWorkflow(
        PluginDirectoryPublisher((examples,), runtime_profile="python-uv"),
        image_builder,
        releases,
        load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH),
    )
    candidate = await publication.verify(
        examples / "plugin-notes", expected_slug="notes"
    )
    if base_revision:
        await releases.publish(
            workspace_id=WORKSPACE_ID,
            catalog=candidate.catalog,
            capabilities=candidate.capabilities,
            source_archive=b"base release",
            lock_digest=candidate.lock_digest,
            runtime_profile=candidate.runtime_profile,
            runtime_artifact=None,
            published_by_user_id=ACTOR_ID,
            loader_target=candidate.loader_target,
        )
    pending = asyncio.create_task(
        publication.publish(
            workspace_id=WORKSPACE_ID,
            directory=examples / "plugin-notes",
            expected_slug="notes",
            published_by_user_id=ACTOR_ID,
            reviewed_source_digest=candidate.source_digest,
            reviewed_base_revision=base_revision,
        )
    )
    try:
        await asyncio.wait_for(image_builder.started.wait(), timeout=10)
        competing = await releases.publish(
            workspace_id=WORKSPACE_ID,
            catalog=candidate.catalog,
            capabilities=candidate.capabilities,
            source_archive=b"competing release",
            lock_digest=candidate.lock_digest,
            runtime_profile=candidate.runtime_profile,
            runtime_artifact=None,
            published_by_user_id=ACTOR_ID,
            loader_target=candidate.loader_target,
        )
        image_builder.resume.set()
        with pytest.raises(
            PluginPublicationConflictError, match="head changed after review"
        ):
            await pending
        assert await releases.list_current(WORKSPACE_ID) == [competing]
        async with database.engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(func.count()).select_from(schema.plugin_releases)
                )
                == base_revision + 1
            )
            assert (
                await connection.scalar(
                    select(func.count()).select_from(schema.plugin_installations)
                )
                == base_revision + 1
            )
    finally:
        image_builder.resume.set()
        await asyncio.gather(pending, return_exceptions=True)
        await database.dispose()
