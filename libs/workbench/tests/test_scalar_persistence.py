from typing import cast
from uuid import UUID

import pytest

from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey, JsonObject
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.runtime.resolvers import ResolutionError
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.schema.values import JsonSchemaText
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
def scalar_runtime() -> tuple[ArtifactValues, InMemoryUnitOfWork]:
    uow = InMemoryUnitOfWork()
    values = ArtifactValues(
        (*VALUE.artifacts, *TEXT.artifacts, *SCHEMAS.artifacts),
        uow=uow,
        storage=cast(FileStoragePort, object()),
        bucket="artifacts",
        storage_backend="local",
    )
    return values, uow


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
            JsonSchemaText(value=SCHEMA_INPUT),
            {"value": SCHEMA_VALUE},
            "96120c2d66cc9778b1cbc670dbfd9fda9bec6df075a3d29f60aa68f330e949fd",
            107,
        ),
    ],
)
async def test_scalar_artifacts_match_original_writer_bytes(
    scalar_runtime: tuple[ArtifactValues, InMemoryUnitOfWork],
    key: ArtifactTypeKey,
    value: object,
    expected_payload: JsonObject,
    expected_sha256: str,
    expected_size: int,
    with_provenance: bool,
) -> None:
    values, uow = scalar_runtime
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

    ref = await values.write(key, value, context)
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
        # producer_node_id is applied after context metadata, so the node id wins.
        "producer_node_id": "scalar",
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
    assert artifact.metadata == expected_metadata, (
        "metadata order is context metadata, then producer_node_id, "
        "then provenance, then type-owned keys"
    )
    stored_value = expected_payload["value"]
    if key == JSON_SCHEMA.key:
        assert isinstance(stored_value, str)
        expected: object = JsonSchemaText(value=stored_value)
    else:
        expected = stored_value
    assert await values.resolve(ref, WORKSPACE_ID) == expected


@pytest.mark.parametrize(
    "key,value,error",
    [
        (INTEGER_VALUE.key, True, TypeError),
        (TEXT_VALUE.key, 42, TypeError),
        (JSON_SCHEMA.key, JsonSchemaText(value='{"type":"array"}'), ValueError),
    ],
)
async def test_scalar_writer_propagates_validation_errors(
    scalar_runtime: tuple[ArtifactValues, InMemoryUnitOfWork],
    key: ArtifactTypeKey,
    value: object,
    error: type[Exception],
) -> None:
    values, _ = scalar_runtime
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="invalid"),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    with pytest.raises(error):
        _ = await values.write(key, value, context)


async def test_scalar_writer_preserves_storage_failure(
    scalar_runtime: tuple[ArtifactValues, InMemoryUnitOfWork],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values, uow = scalar_runtime
    failure = OSError("storage unavailable")

    async def fail_commit() -> None:
        raise failure

    monkeypatch.setattr(uow, "commit", fail_commit)
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="storage"),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    with pytest.raises(OSError) as raised:
        _ = await values.write(INTEGER_VALUE.key, 42, context)
    assert raised.value is failure


async def test_schema_resolver_checks_stored_schema_and_preserves_cause(
    scalar_runtime: tuple[ArtifactValues, InMemoryUnitOfWork],
) -> None:
    values, uow = scalar_runtime
    context = ArtifactWriteContext(
        node_context=NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="schema"),
        provenance=MaterializationProvenance(refs_by_input={}),
    )
    ref = await values.write(
        JSON_SCHEMA.key, JsonSchemaText(value=SCHEMA_INPUT), context
    )
    async with uow as entered:
        artifact = await entered.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert artifact is not None
        artifact.inline_payload = {"value": '{"type":"array"}'}
        await entered.commit()

    with pytest.raises(ResolutionError, match=str(ref.artifact_id)) as raised:
        _ = await values.resolve(ref, WORKSPACE_ID)
    assert isinstance(raised.value.__cause__, ValueError)
    assert "must declare type='object'" in str(raised.value.__cause__)
