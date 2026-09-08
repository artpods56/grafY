from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from grafy_core.artifact_collections import (
    JSON_COLLECTIONS_STORAGE_FORMAT,
    JsonCollection,
    load_json_collections_manifest,
    save_json_collections,
)
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeKey,
    InMemoryUnitOfWork,
)
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.nodes import NodeExecutionContext
from grafy_core.table_contracts import (
    Table,
    TableColumn,
    TableValueType,
)
from grafy_core.runtime.table_storage import load_table_manifest
from grafy_workbench.table.persistence import TableArtifactWriter
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.ports.storage import SaveFileCommand, StoredObjectInfo
from grafy_core.domain.identity import Workspace
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore

from grafy_api.execution.requests import RunRequest
from tests.support.clients import GrafyApi
from tests.support.system_plugins import (
    build_selected_system_plugin_deployment,
    selected_system_run_node as RunNodeRequest,
)
from grafy_core.runtime.persistent_invocation_cache import (
    InvocationCacheAccessError,
    PersistentInvocationCache,
)
from grafy_api.services.composition import build_workbench_components

from tests.testkit import create_db_url, db


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


async def _raise_storage_outage(bucket: str, path: str) -> StoredObjectInfo | None:
    raise RuntimeError(f"Storage unavailable for {bucket}/{path}")


def _run_output_artifact_id(
    client: TestClient,
    *,
    node_id: str,
    operator_id: str,
    config: dict[str, object],
    plugin_slug: str | None = None,
) -> str:
    api = GrafyApi(client)
    executions = api.workspace(UUID("00000000-0000-0000-0000-000000000007")).executions
    response = executions.run(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id=node_id,
                    operator_id=operator_id,
                    operator_version=1,
                    config=config,
                    plugin_slug=plugin_slug,
                )
            ]
        )
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "succeeded"
    return str(body["node_runs"][0]["outputs"][0]["value"]["artifact_id"])


def test_exact_builtin_reuses_artifact_for_the_same_invocation(
    builtin_client: TestClient,
) -> None:
    first = _run_output_artifact_id(
        builtin_client,
        node_id="text-source",
        operator_id="text.input",
        config={"text": "stable value"},
    )
    repeated = _run_output_artifact_id(
        builtin_client,
        node_id="text-source",
        operator_id="text.input",
        config={"text": "stable value"},
    )
    changed_config = _run_output_artifact_id(
        builtin_client,
        node_id="text-source",
        operator_id="text.input",
        config={"text": "changed value"},
    )
    changed_node = _run_output_artifact_id(
        builtin_client,
        node_id="other-text-source",
        operator_id="text.input",
        config={"text": "stable value"},
    )

    assert repeated == first
    assert changed_config != first
    assert changed_node != first


def test_external_node_default_policy_does_not_reuse_results(
    structural_projection_client: TestClient,
) -> None:
    first = _run_output_artifact_id(
        structural_projection_client,
        node_id="external",
        operator_id="test.api_response",
        config={},
        plugin_slug="test.structural-projection",
    )
    repeated = _run_output_artifact_id(
        structural_projection_client,
        node_id="external",
        operator_id="test.api_response",
        config={},
        plugin_slug="test.structural-projection",
    )

    assert repeated != first


async def test_cache_evicts_an_entry_with_a_missing_artifact(tmp_path: Path) -> None:
    unit_of_work = InMemoryUnitOfWork()
    missing_artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000301"),
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": "missing"},
        sha256="a" * 64,
    )
    entry = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="b" * 64,
        outputs={"text": missing_artifact.ref()},
    )
    async with unit_of_work as entered:
        assert await entered.invocation_cache.put_if_absent(entry)
        await entered.commit()

    cache = PersistentInvocationCache(
        unit_of_work=unit_of_work,
        storage=LocalFileObjectStore(tmp_path / "objects"),
    )
    assert await cache.get(WORKSPACE_ID, entry.key_sha256) is None
    async with unit_of_work as entered:
        assert (
            await entered.invocation_cache.get(WORKSPACE_ID, entry.key_sha256) is None
        )


async def test_storage_outage_preserves_the_cache_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000311"),
        artifact_type="image.raster",
        schema_version=1,
        content_type="image/png",
        storage_backend="local",
        bucket="artifacts",
        object_key="cached.png",
        byte_size=12,
        sha256="c" * 64,
    )
    entry = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="d" * 64,
        outputs={"image": artifact.ref()},
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        assert await entered.invocation_cache.put_if_absent(entry)
        await entered.commit()

    storage = LocalFileObjectStore(tmp_path / "objects")
    monkeypatch.setattr(storage, "stat", _raise_storage_outage)
    cache = PersistentInvocationCache(
        unit_of_work=unit_of_work,
        storage=storage,
    )
    with pytest.raises(InvocationCacheAccessError, match=str(artifact.id)):
        await cache.get(WORKSPACE_ID, entry.key_sha256)

    async with unit_of_work as entered:
        preserved = await entered.invocation_cache.get(WORKSPACE_ID, entry.key_sha256)
    assert preserved is not None
    assert preserved.generation == entry.generation


async def test_cache_evicts_a_table_with_a_missing_chunk(tmp_path: Path) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    writer = TableArtifactWriter(
        storage=storage,
        uow=unit_of_work,
        bucket="artifacts",
        storage_backend="local",
    )
    ref = await writer.write(
        Table(
            columns=[
                TableColumn(
                    id="row",
                    title="Row",
                    value_type=TableValueType.INTEGER,
                )
            ],
            rows=[{"row": index} for index in range(205)],
        ),
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                node_id="table",
                workspace_id=WORKSPACE_ID,
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    entry = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="e" * 64,
        outputs={"table": ref},
    )
    async with unit_of_work as uow:
        assert await uow.invocation_cache.put_if_absent(entry)
        artifact = await uow.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        await uow.commit()
    assert artifact is not None
    assert artifact.bucket is not None
    manifest = await load_table_manifest(artifact, storage)
    await storage.delete(artifact.bucket, manifest.chunks[1].object_key)

    cache = PersistentInvocationCache(
        unit_of_work=unit_of_work,
        storage=storage,
    )
    assert await cache.get(WORKSPACE_ID, entry.key_sha256) is None
    async with unit_of_work as uow:
        assert await uow.invocation_cache.get(WORKSPACE_ID, entry.key_sha256) is None


async def test_cache_evicts_a_json_collection_with_a_corrupt_chunk(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    artifact_type = ArtifactTypeKey(id="geo.feature_collection", schema_version=1)
    stored = await save_json_collections(
        storage,
        bucket="artifacts",
        artifact_type=artifact_type,
        collections=[
            JsonCollection(
                id="features",
                items=[{"type": "Feature", "id": index} for index in range(60)],
            )
        ],
        metadata={
            "kind": "geo.feature_collection",
            "source_name": "Cached features",
            "bounds": None,
        },
        node_id="features",
        workspace_id=UUID("00000000-0000-0000-0000-000000000901"),
    )
    artifact = ArtifactObject(
        workspace_id=UUID("00000000-0000-0000-0000-000000000901"),
        artifact_type=artifact_type.id,
        schema_version=artifact_type.schema_version,
        content_type="application/geo+json",
        storage_backend="local",
        bucket=stored.bucket,
        object_key=stored.manifest_path,
        sha256="f" * 64,
        metadata={
            "storage_format": JSON_COLLECTIONS_STORAGE_FORMAT,
            "manifest_byte_size": stored.manifest_byte_size,
            "manifest_sha256": stored.manifest_sha256,
        },
    )
    entry = InvocationCacheEntry(
        workspace_id=WORKSPACE_ID,
        key_sha256="1" * 64,
        outputs={"features": artifact.ref()},
    )
    async with unit_of_work as uow:
        await uow.artifacts.add(artifact)
        assert await uow.invocation_cache.put_if_absent(entry)
        await uow.commit()
    manifest = await load_json_collections_manifest(artifact, storage)
    chunk = manifest.collections[0].chunks[0]
    await storage.save(
        SaveFileCommand(
            bucket=stored.bucket,
            path=chunk.object_key,
            stream=BytesIO(b"{}"),
            content_type="application/json",
            metadata={},
            allow_overwrite=True,
        )
    )

    cache = PersistentInvocationCache(
        unit_of_work=unit_of_work,
        storage=storage,
    )
    assert await cache.get(WORKSPACE_ID, entry.key_sha256) is None
    async with unit_of_work as uow:
        assert await uow.invocation_cache.get(WORKSPACE_ID, entry.key_sha256) is None


async def test_sql_cache_survives_fresh_workbench_components(tmp_path: Path) -> None:
    database_url = create_db_url(tmp_path, "persistent-cache.sqlite3")
    async with db(database_url) as database:
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.identity.add_workspace(
                Workspace(
                    id=WORKSPACE_ID,
                    slug="cache-test",
                    name="Cache test workspace",
                    kind="shared",
                )
            )
            await unit_of_work.commit()
        deployment = build_selected_system_plugin_deployment()
        registry = deployment.registry
        request = RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="persistent-text",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "survives restart"},
                )
            ]
        )

        first_components = build_workbench_components(
            plugin_registry=registry,
            workspace=tmp_path / "workbench",
            unit_of_work=SqlAlchemyUnitOfWork(database.sessions),
            plugin_releases=cast(PluginReleaseService, deployment.release_lookup),
        )
        first_response = await first_components.presenter.run_response(
            WORKSPACE_ID,
            await first_components.run_graph.run(WORKSPACE_ID, request),
        )
        first_value = first_response.node_runs[0].outputs[0].value
        assert isinstance(first_value, ArtifactRef)

        fresh_components = build_workbench_components(
            plugin_registry=registry,
            workspace=tmp_path / "workbench",
            unit_of_work=SqlAlchemyUnitOfWork(database.sessions),
            plugin_releases=cast(PluginReleaseService, deployment.release_lookup),
        )
        repeated_response = await fresh_components.presenter.run_response(
            WORKSPACE_ID,
            await fresh_components.run_graph.run(WORKSPACE_ID, request),
        )
        repeated_value = repeated_response.node_runs[0].outputs[0].value
        assert isinstance(repeated_value, ArtifactRef)

        assert repeated_value == first_value
