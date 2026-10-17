import asyncio
from pathlib import Path
import shutil

from pydantic import SecretStr

from grafy_shared.config import AppConfig

from grafy_api.plugins.publication.source import PluginDirectoryPublisher
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
    PluginExecutionPolicy,
    PluginRuntimeArtifact,
)
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import (
    browser_actor_override,
    create_schema,
    workspace_api_path,
)
from tests.testkit import client_with_overrides


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLATFORM_ACTOR = PlatformPluginActor("test:platform")


def _runtime_artifact(name: str, digest: str) -> PluginRuntimeArtifact:
    return PluginRuntimeArtifact(
        object_key=f"plugin-releases/notes/runtime/{name}.oci.tar",
        archive_digest=digest * 64,
        manifest_digest=digest * 64,
        config_digest=digest * 64,
    )


def test_published_system_release_is_overlaid_in_the_node_catalog(
    tmp_path: Path,
) -> None:
    """A frozen Plugin project reaches the catalog only through publish and promote."""

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'catalog.sqlite3'}"
    asyncio.run(create_schema(database_url))
    database = create_database(database_url)
    verified = PluginDirectoryPublisher(
        (REPOSITORY_ROOT / "tests" / "fixtures",), runtime_profile="python-uv"
    ).verify(REPOSITORY_ROOT / "tests" / "fixtures" / "plugin-notes")
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "workbench" / "objects"),
        bucket="workbench-artifacts",
    )

    async def publish(
        artifact: PluginRuntimeArtifact,
        *,
        catalog=verified.catalog,
        archive: bytes = verified.source_archive,
        runtime_profile: str = "python-uv",
    ):
        return await service.publish_system(
            catalog=catalog,
            capabilities=verified.capabilities,
            source_archive=archive,
            lock_digest=verified.lock_digest,
            runtime_profile=runtime_profile,
            runtime_artifact=artifact,
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            platform_actor=PLATFORM_ACTOR,
            loader_target=verified.loader_target,
        )

    first = asyncio.run(publish(_runtime_artifact("first", "1")))
    repeat = asyncio.run(publish(_runtime_artifact("first", "1")))
    assert repeat == first
    assert first.release.executable is True

    changed_image = asyncio.run(publish(_runtime_artifact("changed", "4")))
    assert changed_image.release.revision == 2

    changed_profile = asyncio.run(
        publish(_runtime_artifact("first", "1"), runtime_profile="python-uv-gdal")
    )
    assert changed_profile.release.revision == 3

    changed_copy = tmp_path / "changed-plugin"
    changed_copy.mkdir()
    for entry in ("pyproject.toml", "uv.lock", "wheels", "src", "tests"):
        source = REPOSITORY_ROOT / "tests" / "fixtures" / "plugin-notes" / entry
        target = changed_copy / entry
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    nodes_path = changed_copy / "src" / "grafy_plugin" / "declaration.py"
    nodes_path.write_text(
        nodes_path.read_text(encoding="utf-8") + "\n# changed\n",
        encoding="utf-8",
    )
    changed_verified = PluginDirectoryPublisher(
        (tmp_path,), runtime_profile="python-uv"
    ).verify(changed_copy)
    assert changed_verified.source_archive != verified.source_archive
    changed_source = asyncio.run(
        publish(
            _runtime_artifact("first", "1"),
            catalog=changed_verified.catalog,
            archive=changed_verified.source_archive,
        )
    )
    assert changed_source.release.revision == 4

    # Publication alone changes nothing: the catalog follows the selection.
    settings = Settings(
        app=AppConfig(
            workspace=tmp_path / "workbench", database_url=SecretStr(database_url)
        )
    )
    try:
        with client_with_overrides(
            settings=settings,
            overrides={
                browser_actor: browser_actor_override,
                workspace_actor: browser_actor_override,
            },
        ) as client:
            staged_slugs = {
                plugin["slug"]
                for plugin in client.get(workspace_api_path("/nodes")).json()["plugins"]
            }
            assert "notes" not in staged_slugs

            asyncio.run(
                service.promote_system(
                    slug=changed_source.release.slug,
                    revision=changed_source.release.revision,
                    platform_actor=PLATFORM_ACTOR,
                    expected_generation=0,
                )
            )

            response = client.get(workspace_api_path("/nodes"))
            assert response.status_code == 200
            payload = response.json()
    finally:
        asyncio.run(database.dispose())

    notes_plugin = next(
        plugin for plugin in payload["plugins"] if plugin["slug"] == "notes"
    )
    assert notes_plugin["publisher"] == "test:platform"
    assert notes_plugin["scope"] == "system"
    assert notes_plugin["installation_scope"] == "system"
    assert notes_plugin["plugin_release"] == {
        "scope": "system",
        "slug": "notes",
        "revision": 4,
    }
    assert notes_plugin["revision"] == 4
    notes_nodes = {
        node["operator_id"]: node
        for node in payload["nodes"]
        if node["plugin_slug"] == "notes"
    }
    assert set(notes_nodes) == {
        "notes.table.summarize",
        "notes.summary.render",
    }
    assert all(node["plugin_revision"] == 4 for node in notes_nodes.values())
    # This deployment runs no adapter for the release's runtime profile, so the
    # catalog reports the same reason the compiler would refuse it.
    assert all(node["runnable"] is False for node in notes_nodes.values())
    assert all(
        node["non_runnable_reason"] == "unsupported_runtime_profile"
        for node in notes_nodes.values()
    )
    assert any(
        artifact["key"] == {"id": "notes.table_summary", "schema_version": 1}
        for artifact in payload["artifact_types"]
    )
