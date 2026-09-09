from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import (
    ArtifactFieldProjection,
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.canonical_conversions import INTEGER_TO_TEXT
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.nodes import resolve_node_contracts
from grafy_workbench.arithmetic.nodes import (
    INTEGER_VALUE,
    IntegerValueOutputWriter,
    IntegerValueResolver,
)
from grafy_workbench.sequence.nodes import CollectNode
from grafy_workbench.text.nodes import (
    TEXT_VALUE,
    ReplaceTextNode,
    TextValueOutputWriter,
    TextValueResolver,
)
from grafy_core.runtime.invocation import InvocationMode, NodeInvocation
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriterRegistry,
)
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry
from grafy_storage import LocalFileObjectStore

from grafy_api.artifact_availability import ArtifactAvailability
from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    FieldProjectionRequest,
    RunEdgeRequest,
    RunInputPlugRequest,
    RunNodeRequest,
)
from grafy_api.v1.routes.artifacts.services import ArtifactService
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.models import (
    CompiledEdge,
    CompiledNode,
)


SOURCE_RESPONSE = ArtifactTypeKey("test.edge_values.response", 1)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
RETRY_COUNT_PROJECTION = ArtifactFieldProjection(
    path=("customer", "retry_count"),
    target=INTEGER_VALUE.key,
    title="Retry count",
)


def _fail_integer_to_text(_value: int) -> str:
    raise ValueError("conversion failed deliberately")


FAILING_INTEGER_TO_TEXT = ArtifactConversion(
    key=ArtifactConversionKey("test.edge_values.fail", 1),
    source=INTEGER_VALUE.key,
    target=TEXT_VALUE.key,
    source_type=int,
    target_type=str,
    title="Fail deliberately",
    convert=_fail_integer_to_text,
)


def _edge_value_resolver(
    unit_of_work: InMemoryUnitOfWork,
    tmp_path: Path,
) -> tuple[EdgeValueResolver, ArtifactService]:
    resolvers = ResolverRegistry(
        [
            cast(Resolver[object], IntegerValueResolver(uow=unit_of_work)),
            cast(Resolver[object], TextValueResolver(uow=unit_of_work)),
        ]
    )
    writers = ArtifactWriterRegistry(
        [
            cast(
                ArtifactOutputWriter,
                IntegerValueOutputWriter(uow=unit_of_work),
            ),
            cast(
                ArtifactOutputWriter,
                TextValueOutputWriter(uow=unit_of_work),
            ),
        ]
    )
    artifacts = ArtifactService(
        unit_of_work,
        LocalFileObjectStore(tmp_path / "objects"),
        availability=ArtifactAvailability(
            unit_of_work, LocalFileObjectStore(tmp_path / "objects")
        ),
    )
    return (
        EdgeValueResolver(
            resolvers=resolvers,
            writers=writers,
            artifacts=artifacts,
        ),
        artifacts,
    )


def _compiled_replace(invocation: NodeInvocation) -> CompiledNode:
    node = ReplaceTextNode()
    return CompiledNode(
        request=RunNodeRequest(
            kind="builtin",
            id="target",
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            config={"search": "unused", "replacement": "unused"},
        ),
        node=node,
        registration=None,
        resolved_contracts=resolve_node_contracts(node, {}),
        invocation=invocation,
        artifact_type_bindings={},
    )


@pytest.mark.asyncio
async def test_instance_plugs_follow_declared_order_and_ignore_other_targets(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    edge_values, _artifacts = _edge_value_resolver(unit_of_work, tmp_path)
    first_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=TEXT_VALUE.key)
    second_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=TEXT_VALUE.key)
    unrelated_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=TEXT_VALUE.key)
    node = CollectNode()
    compiled_node = CompiledNode(
        request=RunNodeRequest(
            kind="builtin",
            id="collect",
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            input_plugs=[
                RunInputPlugRequest(id="second", port="items"),
                RunInputPlugRequest(id="first", port="items"),
            ],
        ),
        node=node,
        registration=None,
        resolved_contracts=resolve_node_contracts(node, {"T": TEXT_VALUE.key}),
        invocation=NodeInvocation(),
        artifact_type_bindings={"T": TEXT_VALUE.key},
    )
    first_edge = CompiledEdge(
        request=RunEdgeRequest(
            from_node="first-source",
            from_port="value",
            to_node="collect",
            to_port="items",
            to_plug="first",
        ),
        projection=None,
        conversion_path=(),
    )
    second_edge = CompiledEdge(
        request=RunEdgeRequest(
            from_node="second-source",
            from_port="value",
            to_node="collect",
            to_port="items",
            to_plug="second",
        ),
        projection=None,
        conversion_path=(),
    )
    unrelated_edge = CompiledEdge(
        request=RunEdgeRequest(
            from_node="unrelated-source",
            from_port="value",
            to_node="other-target",
            to_port="items",
            to_plug="second",
        ),
        projection=None,
        conversion_path=(),
    )

    inputs = await edge_values.assemble_inputs(
        compiled_node,
        (first_edge, second_edge, unrelated_edge),
        {
            "first-source": {"value": first_ref},
            "second-source": {"value": second_ref},
            "unrelated-source": {"value": unrelated_ref},
        },
        uuid4(),
        WORKSPACE_ID,
    )

    assert inputs["items"] == [second_ref, first_ref]


@pytest.mark.asyncio
async def test_projection_precedes_conversion_and_preserves_sequence_context(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    edge_values, artifacts = _edge_value_resolver(unit_of_work, tmp_path)
    first_source = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=SOURCE_RESPONSE.id,
        schema_version=SOURCE_RESPONSE.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"customer": {"retry_count": 7}},
    )
    second_source = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=SOURCE_RESPONSE.id,
        schema_version=SOURCE_RESPONSE.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"customer": {"retry_count": 12}},
    )
    async with unit_of_work as transaction:
        await transaction.artifacts.add(first_source)
        await transaction.artifacts.add(second_source)
        await transaction.commit()

    source_sequence = ArtifactRefSequence(
        artifact_type=SOURCE_RESPONSE.id,
        schema_version=SOURCE_RESPONSE.schema_version,
        item_refs=[first_source.ref(), second_source.ref()],
        ordered=False,
        index_key="page_number",
        metadata={"caller": "preserved"},
    )
    compiled_node = _compiled_replace(
        NodeInvocation(mode=InvocationMode.MAP, map_input="text")
    )
    edge = CompiledEdge(
        request=RunEdgeRequest(
            from_node="source",
            from_port="response",
            to_node="target",
            to_port="text",
            projection=FieldProjectionRequest(path=list(RETRY_COUNT_PROJECTION.path)),
            conversion_path=[
                ArtifactConversionRequest(
                    id=INTEGER_TO_TEXT.key.id,
                    version=INTEGER_TO_TEXT.key.version,
                )
            ],
            collection_mode="map",
        ),
        projection=RETRY_COUNT_PROJECTION,
        conversion_path=(INTEGER_TO_TEXT,),
    )

    inputs = await edge_values.assemble_inputs(
        compiled_node,
        (edge,),
        {"source": {"response": source_sequence}},
        uuid4(),
        WORKSPACE_ID,
    )

    converted = inputs["text"]
    assert isinstance(converted, ArtifactRefSequence)
    text_resolver = TextValueResolver(uow=unit_of_work)
    assert [
        await text_resolver.resolve(item_ref, WORKSPACE_ID)
        for item_ref in converted.item_refs
    ] == ["7", "12"]
    assert converted.ordered is False
    assert converted.index_key == "page_number"
    assert converted.metadata["caller"] == "preserved"
    assert converted.metadata["projection_path"] == ["customer", "retry_count"]
    assert converted.metadata["projection_title"] == "Retry count"
    assert converted.metadata["conversion_path"] == [
        {"id": INTEGER_TO_TEXT.key.id, "version": INTEGER_TO_TEXT.key.version}
    ]
    assert converted.metadata["conversion_titles"] == [INTEGER_TO_TEXT.title]
    projected_sequence_id = converted.metadata["source_sequence_id"]
    assert isinstance(projected_sequence_id, str)
    assert UUID(projected_sequence_id) != source_sequence.sequence_id

    final_artifact = await artifacts.get(
        WORKSPACE_ID,
        converted.item_refs[0].artifact_id,
    )
    assert final_artifact is not None
    projected_artifact_id = final_artifact.metadata["source_artifact_id"]
    assert isinstance(projected_artifact_id, str)
    projected_artifact = await artifacts.get(
        WORKSPACE_ID,
        UUID(projected_artifact_id),
    )
    assert projected_artifact is not None
    assert projected_artifact.id != first_source.id
    assert projected_artifact.metadata["source_artifact_id"] == str(first_source.id)
    assert projected_artifact.metadata["producer_node_id"] == "source"
    assert final_artifact.metadata["producer_node_id"] == "source"
    assert projected_artifact.metadata["provenance"] == {
        "response": [
            {
                "artifact_id": str(first_source.id),
                "artifact_type": SOURCE_RESPONSE.id,
                "schema_version": SOURCE_RESPONSE.schema_version,
            }
        ]
    }
    assert final_artifact.metadata["provenance"] == {
        "response": [
            {
                "artifact_id": str(projected_artifact.id),
                "artifact_type": INTEGER_VALUE.key.id,
                "schema_version": INTEGER_VALUE.key.schema_version,
            }
        ]
    }


@pytest.mark.asyncio
async def test_conversion_failure_identifies_step_item_artifact_and_edge(
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    edge_values, _artifacts = _edge_value_resolver(unit_of_work, tmp_path)
    source = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type=INTEGER_VALUE.key.id,
        schema_version=INTEGER_VALUE.key.schema_version,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 3},
    )
    async with unit_of_work as transaction:
        await transaction.artifacts.add(source)
        await transaction.commit()

    compiled_node = _compiled_replace(
        NodeInvocation(mode=InvocationMode.MAP, map_input="text")
    )
    edge = CompiledEdge(
        request=RunEdgeRequest(
            from_node="source",
            from_port="value",
            to_node="target",
            to_port="text",
            conversion_path=[
                ArtifactConversionRequest(
                    id=FAILING_INTEGER_TO_TEXT.key.id,
                    version=FAILING_INTEGER_TO_TEXT.key.version,
                )
            ],
            collection_mode="map",
        ),
        projection=None,
        conversion_path=(FAILING_INTEGER_TO_TEXT,),
    )

    with pytest.raises(GraphExecutionError) as captured:
        await edge_values.assemble_inputs(
            compiled_node,
            (edge,),
            {
                "source": {
                    "value": ArtifactRefSequence.from_key(
                        key=INTEGER_VALUE.key,
                        item_refs=[source.ref()],
                    )
                }
            },
            uuid4(),
            WORKSPACE_ID,
        )

    message = str(captured.value)
    assert "Failed conversion step 1/1 'test.edge_values.fail'@1" in message
    assert f"artifact {source.id} at sequence item 0" in message
    assert "on edge 'source'.'value' -> 'target'.'text'" in message
    assert isinstance(captured.value.__cause__, ValueError)
