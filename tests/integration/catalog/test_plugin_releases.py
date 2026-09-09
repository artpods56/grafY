import asyncio
from pathlib import Path
import shutil

from pydantic import SecretStr

from grafy_api.plugins.publication.source import PluginDirectoryPublisher
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_releases import PluginRuntimeArtifact
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import (
    TEST_USER_ID,
    WORKSPACE_ID,
    browser_actor_override,
    create_schema,
    workspace_api_path,
)
from tests.testkit import client_with_overrides


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_workspace_plugin_release_is_overlaid_in_node_catalog(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'catalog.sqlite3'}"
    asyncio.run(create_schema(database_url))
    database = create_database(database_url)
    verified = PluginDirectoryPublisher(
        (REPOSITORY_ROOT / "examples",), runtime_profile="python-uv"
    ).verify(REPOSITORY_ROOT / "examples" / "plugin-notes")
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "workbench" / "objects"),
        bucket="workbench-artifacts",
    )
    release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            runtime_artifact=None,
            loader_target=verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    same_release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            runtime_artifact=None,
            loader_target=verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    assert same_release == release
    first_runtime_artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/notes/runtime/first.oci.tar",
        archive_digest="1" * 64,
        manifest_digest="2" * 64,
        config_digest="3" * 64,
    )
    image_backed_release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            runtime_artifact=first_runtime_artifact,
            loader_target=verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    assert image_backed_release.release.revision == 2
    assert image_backed_release.release.executable is True
    assert release.release.executable is False
    same_image_backed_release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            runtime_artifact=first_runtime_artifact,
            loader_target=verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    assert same_image_backed_release == image_backed_release
    changed_image_release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            runtime_artifact=PluginRuntimeArtifact(
                object_key="plugin-releases/notes/runtime/changed.oci.tar",
                archive_digest="4" * 64,
                manifest_digest="5" * 64,
                config_digest="6" * 64,
            ),
            loader_target=verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    assert changed_image_release.release.revision == 3
    changed_profile_release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=verified.catalog,
            capabilities=verified.capabilities,
            source_archive=verified.source_archive,
            lock_digest=verified.lock_digest,
            runtime_profile="python-uv-gdal",
            runtime_artifact=None,
            loader_target=verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    assert changed_profile_release.release.revision == 4

    changed_copy = tmp_path / "changed-plugin"
    changed_copy.mkdir()
    for entry in ("pyproject.toml", "uv.lock", "wheels", "src", "tests"):
        source = REPOSITORY_ROOT / "examples" / "plugin-notes" / entry
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
    changed_release = asyncio.run(
        service.publish(
            workspace_id=WORKSPACE_ID,
            catalog=changed_verified.catalog,
            capabilities=changed_verified.capabilities,
            source_archive=changed_verified.source_archive,
            lock_digest=changed_verified.lock_digest,
            runtime_profile=changed_verified.runtime_profile,
            runtime_artifact=None,
            loader_target=changed_verified.loader_target,
            published_by_user_id=TEST_USER_ID,
        )
    )
    assert changed_release.release.revision == 5

    settings = Settings(
        workspace=tmp_path / "workbench",
        database_url=SecretStr(database_url),
    )
    try:
        with client_with_overrides(
            settings=settings,
            overrides={
                browser_actor: browser_actor_override,
                workspace_actor: browser_actor_override,
            },
        ) as client:
            response = client.get(workspace_api_path("/nodes"))
            assert response.status_code == 200
            payload = response.json()
    finally:
        asyncio.run(database.dispose())

    notes_plugin = next(
        plugin for plugin in payload["plugins"] if plugin["slug"] == "notes"
    )
    assert notes_plugin == {
        "slug": "notes",
        "title": "Notes",
        "origin": "plugin",
        "entry_kind": "plugin",
        "scope": "workspace",
        "plugin_release": {
            "scope": "workspace",
            "slug": "notes",
            "revision": 5,
        },
        "revision": 5,
        "publisher": str(TEST_USER_ID),
        "installation_scope": "workspace",
        "runnable": False,
        "non_runnable_reason": "missing_runtime_artifact",
        "non_runnable_detail": "This release has no immutable runtime image.",
    }
    notes_nodes = {
        node["operator_id"]: node
        for node in payload["nodes"]
        if node["plugin_slug"] == "notes"
    }
    assert set(notes_nodes) == {
        "notes.table.summarize",
        "notes.summary.render",
    }
    assert all(node["plugin_revision"] == 5 for node in notes_nodes.values())
    assert all(node["runnable"] is False for node in notes_nodes.values())
    assert all(
        node["non_runnable_reason"] == "missing_runtime_artifact"
        for node in notes_nodes.values()
    )
    assert any(
        artifact["key"] == {"id": "notes.table_summary", "schema_version": 1}
        for artifact in payload["artifact_types"]
    )
