from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey, JsonObject
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriterRegistry, ArtifactWriteContext
from grafy_core.runtime.resolvers import ResolutionError, ResolverRegistry
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.text import TEXT
from grafy_workbench.value import VALUE

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
SCHEMA_INPUT = (
    '{ "type": "object", "properties": {"café": {"type": "string"}}, '
    '"required": ["café"] }'
)
SCHEMA_VALUE = (
    '{"type":"object","properties":{"café":{"type":"string"}},"required":["café"]}'
)


@pytest.fixture
def scalar_runtime(
    tmp_path: Path,
) -> tuple[ArtifactWriterRegistry, ResolverRegistry, InMemoryUnitOfWork]:
    uow = InMemoryUnitOfWork()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=cast(FileStoragePort, object()),
        uow=uow,
        bucket="artifacts",
    )
    registry = PluginRegistry()
    for family in (VALUE, TEXT, SCHEMAS):
        registry.install(family)
    registry.freeze()
    return (
        ArtifactWriterRegistry(list(registry.build_writers(context))),
        ResolverRegistry(list(registry.build_resolvers(context))),
        uow,
    )


@pytest.mark.parametrize("with_provenance", [False, True])
@pytest.mark.parametrize(
    "key,value,expected_payload,expected_sha256,expected_size",
    [
        (
            INTEGER_VALUE.key,
            -42,
            {"value": -42},
            "fba1a125f133e3f2bffea14e675dbb239901421340cde588d8989ee0b8beb79c",
            13,
        ),
        (
            TEXT_VALUE.key,
            'Zażółć 🌍\n"quoted"',
            {"value": 'Zażółć 🌍\n"quoted"'},
            "e17c4236ebc1bfe6977dd570e1677432c11c9e7d2c9f0ab8b74963cf3389e706",
            39,
        ),
        (
            JSON_SCHEMA.key,
            SCHEMA_INPUT,
            {"value": SCHEMA_VALUE},
            "96120c2d66cc9778b1cbc670dbfd9fda9bec6df075a3d29f60aa68f330e949fd",
            107,
        ),
    ],
)
async def test_scalar_artifacts_match_original_writer_bytes(
    scalar_runtime: tuple[ArtifactWriterRegistry, ResolverRegistry, InMemoryUnitOfWork],
    key: ArtifactTypeKey,
    value: object,
    expected_payload: JsonObject,
    expected_sha256: str,
    expected_size: int,
    with_provenance: bool,
) -> None:
    writers, resolvers, uow = scalar_runtime
    source_ref = ArtifactRef(
        artifact_id=UUID("00000000-0000-0000-0000-000000000042"),
        artifact_type="scalar.integer",
        schema_version=1,
    )
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="scalar"),
        provenance=MaterializationProvenance(
            refs_by_input={"input": (source_ref,)} if with_provenance else {},
        ),
        metadata={"producer_node_id": "override", "conversion_version": 1},
    )

    ref = await writers.writer_for(key).write(value, context)
    async with uow as entered:
        artifact = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    assert ref.key() == key
    assert artifact.workspace_id == WORKSPACE_ID
    assert artifact.storage_backend == "inline"
    assert artifact.content_type == "application/json"
    assert artifact.inline_payload == expected_payload
    assert artifact.sha256 == expected_sha256
    assert artifact.byte_size == expected_size
    expected_metadata: JsonObject = {
        "producer_node_id": "override",
        "conversion_version": 1,
    }
    if with_provenance:
        expected_metadata["provenance"] = {
            "input": [
                {
                    "artifact_id": str(source_ref.artifact_id),
                    "artifact_type": "scalar.integer",
                    "schema_version": 1,
                }
            ]
        }
    assert artifact.metadata == expected_metadata
    target = int if key == INTEGER_VALUE.key else str
    assert (
        await resolvers.resolve(ref, target, WORKSPACE_ID) == expected_payload["value"]
    )


@pytest.mark.parametrize(
    "key,value,error",
    [
        (INTEGER_VALUE.key, True, ValidationError),
        (TEXT_VALUE.key, 42, ValidationError),
        (JSON_SCHEMA.key, '{"type":"array"}', ValueError),
    ],
)
async def test_scalar_writer_propagates_validation_errors(
    scalar_runtime: tuple[ArtifactWriterRegistry, ResolverRegistry, InMemoryUnitOfWork],
    key: ArtifactTypeKey,
    value: object,
    error: type[Exception],
) -> None:
    writers, _, _ = scalar_runtime
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="invalid"),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    with pytest.raises(error):
        _ = await writers.writer_for(key).write(value, context)


async def test_scalar_writer_preserves_storage_failure(
    scalar_runtime: tuple[ArtifactWriterRegistry, ResolverRegistry, InMemoryUnitOfWork],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writers, _, uow = scalar_runtime
    failure = OSError("storage unavailable")

    async def fail_commit() -> None:
        raise failure

    monkeypatch.setattr(uow, "commit", fail_commit)
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="storage"),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    with pytest.raises(OSError) as raised:
        _ = await writers.writer_for(INTEGER_VALUE.key).write(42, context)
    assert raised.value is failure


async def test_schema_resolver_checks_stored_schema_and_preserves_cause(
    scalar_runtime: tuple[ArtifactWriterRegistry, ResolverRegistry, InMemoryUnitOfWork],
) -> None:
    writers, resolvers, uow = scalar_runtime
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="schema"),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    ref = await writers.writer_for(JSON_SCHEMA.key).write(SCHEMA_INPUT, context)
    async with uow as entered:
        artifact = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert artifact is not None
        artifact.inline_payload = {"value": '{"type":"array"}'}
        await entered.commit()

    with pytest.raises(ResolutionError, match=str(ref.artifact_id)) as raised:
        _ = await resolvers.resolve(ref, str, WORKSPACE_ID)
    assert isinstance(raised.value.__cause__, ValueError)
    assert "must declare type='object'" in str(raised.value.__cause__)
