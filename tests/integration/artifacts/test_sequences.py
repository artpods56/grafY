import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from grafy_core.artifacts import ArtifactObject, ArtifactRef, ArtifactRefSequence
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.artifact_contracts import RASTER_IMAGE
from grafy_workbench.sequence.nodes import ItemAtConfig, SliceConfig

from grafy_api.v1.models import ArtifactTypeBindingModel, ArtifactTypeKeyResponse
from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    PinnedOutputRequest,
    RunEdgeRequest,
    RunInputPlugRequest,
    RunRequest,
)
from grafy_api.v1.routes.executions.models import RunResponse
from grafy_api.execution.requests import RunNodeRequest as UnpinnedRunNodeRequest
from tests.support.system_plugins import selected_system_run_node as RunNodeRequest

from tests.support.clients import GrafyApi


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")


async def _store_artifacts(
    uow: InMemoryUnitOfWork,
    artifacts: list[ArtifactObject],
) -> None:
    async with uow as entered:
        for artifact in artifacts:
            await entered.artifacts.add(artifact)
        await entered.commit()


def _binding(
    artifact_type: str,
    schema_version: int = 1,
) -> list[ArtifactTypeBindingModel]:
    return [
        ArtifactTypeBindingModel(
            variable="T",
            artifact_type=ArtifactTypeKeyResponse(
                id=artifact_type,
                schema_version=schema_version,
            ),
        )
    ]


def test_registry_declares_sequence_node_contracts(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.get(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/nodes"
    )

    assert response.status_code == 200
    registry = NodeRegistryResponse.model_validate(response.json())
    nodes = {node.operator_id: node for node in registry.nodes}
    collect = nodes["sequence.collect"]
    assert collect.plugin_slug == "sequence"
    assert collect.title == "Collect"
    assert collect.inputs[0].artifact_type is None
    assert collect.inputs[0].artifact_type_variable == "T"
    assert collect.inputs[0].accepted_shapes == ["one", "many"]
    assert collect.inputs[0].instance_plugs is True
    assert collect.outputs[0].artifact_type is None
    assert collect.outputs[0].artifact_type_variable == "T"
    assert collect.outputs[0].shape == "many"

    count = nodes["sequence.count"]
    assert count.title == "Count"
    assert count.inputs[0].name == "items"
    assert count.inputs[0].artifact_type_variable == "T"
    assert count.inputs[0].shape == "many"
    assert count.outputs[0].name == "count"
    assert count.outputs[0].artifact_type is not None
    assert count.outputs[0].artifact_type.id == "scalar.integer"
    assert count.outputs[0].shape == "one"

    slice_node = nodes["sequence.slice"]
    assert slice_node.title == "Slice"
    assert slice_node.config_schema == SliceConfig.model_json_schema()
    assert slice_node.inputs[0].artifact_type_variable == "T"
    assert slice_node.inputs[0].shape == "many"
    assert slice_node.outputs[0].artifact_type_variable == "T"
    assert slice_node.outputs[0].shape == "many"

    item_at = nodes["sequence.item_at"]
    assert item_at.title == "Pick item"
    assert item_at.config_schema == ItemAtConfig.model_json_schema()
    assert item_at.inputs[0].artifact_type_variable == "T"
    assert item_at.inputs[0].shape == "many"
    assert item_at.outputs[0].artifact_type_variable == "T"
    assert item_at.outputs[0].shape == "one"


def test_count_slice_and_item_at_preserve_refs_and_artifact_content(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="numbers",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 10, "count": 4, "step": 10},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="count",
                    operator_id="sequence.count",
                    operator_version=1,
                    config={},
                    artifact_type_bindings=_binding("scalar.integer"),
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="slice",
                    operator_id="sequence.slice",
                    operator_version=1,
                    config={"start": 1, "count": 2},
                    artifact_type_bindings=_binding("scalar.integer"),
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="pick",
                    operator_id="sequence.item_at",
                    operator_version=1,
                    config={"index": 1},
                    artifact_type_bindings=_binding("scalar.integer"),
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="numbers",
                    from_port="values",
                    to_node="count",
                    to_port="items",
                ),
                RunEdgeRequest(
                    from_node="numbers",
                    from_port="values",
                    to_node="slice",
                    to_port="items",
                ),
                RunEdgeRequest(
                    from_node="slice",
                    from_port="items",
                    to_node="pick",
                    to_port="items",
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    runs = {run.node_id: run for run in result.node_runs}
    numbers = runs["numbers"].outputs[0]
    counted = runs["count"].outputs[0]
    sliced = runs["slice"].outputs[0]
    picked = runs["pick"].outputs[0]
    assert isinstance(numbers.value, ArtifactRefSequence)
    assert isinstance(counted.value, ArtifactRef)
    assert isinstance(sliced.value, ArtifactRefSequence)
    assert isinstance(picked.value, ArtifactRef)

    assert sliced.value.item_refs == numbers.value.item_refs[1:3]
    assert sliced.value.sequence_id != numbers.value.sequence_id
    assert sliced.value.index_key == numbers.value.index_key
    assert sliced.value.metadata == {
        "source_sequence_id": str(numbers.value.sequence_id),
        "start": 1,
        "count": 2,
    }
    assert picked.value == numbers.value.item_refs[2]
    assert counted.artifacts[0].text == "4"
    assert artifacts.content(counted.value.artifact_id).json() == {"value": 4}
    assert artifacts.content(picked.value.artifact_id).json() == {"value": 30}


def test_collect_flattens_image_scalar_and_sequence_in_plug_order(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, uow = conversion_path_client
    images = [
        ArtifactObject(
            workspace_id=WORKSPACE_ID,
            artifact_type=RASTER_IMAGE.key.id,
            schema_version=RASTER_IMAGE.key.schema_version,
            content_type="image/png",
            inline_payload={"index": index},
        )
        for index in range(4)
    ]
    asyncio.run(_store_artifacts(uow, images))
    image_sequence = ArtifactRefSequence.from_key(
        key=RASTER_IMAGE.key,
        item_refs=[image.ref() for image in images[1:]],
    )

    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="collect",
                    operator_id="sequence.collect",
                    operator_version=1,
                    config={},
                    input_plugs=[
                        RunInputPlugRequest(id="sequence", port="items"),
                        RunInputPlugRequest(id="single", port="items"),
                    ],
                    artifact_type_bindings=_binding("image.raster"),
                )
            ],
            edges=[
                RunEdgeRequest(
                    from_node="external-sequence",
                    from_port="images",
                    to_node="collect",
                    to_port="items",
                    to_plug="sequence",
                ),
                RunEdgeRequest(
                    from_node="external-single",
                    from_port="image",
                    to_node="collect",
                    to_port="items",
                    to_plug="single",
                ),
            ],
            pinned_outputs=[
                PinnedOutputRequest(
                    from_node="external-sequence",
                    from_port="images",
                    value=image_sequence,
                ),
                PinnedOutputRequest(
                    from_node="external-single",
                    from_port="image",
                    value=images[0].ref(),
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    output = result.node_runs[0].outputs[0]
    assert isinstance(output.value, ArtifactRefSequence)
    assert output.value.artifact_type == "image.raster"
    assert [ref.artifact_id for ref in output.value.item_refs] == [
        images[1].id,
        images[2].id,
        images[3].id,
        images[0].id,
    ]
    assert output.value.metadata == {
        "collect_segments": [
            {
                "input_index": 0,
                "start_index": 0,
                "item_count": 3,
                "source_kind": "sequence",
            },
            {
                "input_index": 1,
                "start_index": 3,
                "item_count": 1,
                "source_kind": "single",
            },
        ]
    }


def test_collect_converts_each_input_to_its_bound_text_type(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="number",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 42},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="text",
                    operator_id="text.input",
                    operator_version=1,
                    config={"text": "answer"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="collect",
                    operator_id="sequence.collect",
                    operator_version=1,
                    config={},
                    input_plugs=[
                        RunInputPlugRequest(id="number", port="items"),
                        RunInputPlugRequest(id="text", port="items"),
                    ],
                    artifact_type_bindings=_binding("scalar.text"),
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="number",
                    from_port="value",
                    to_node="collect",
                    to_port="items",
                    to_plug="number",
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        )
                    ],
                ),
                RunEdgeRequest(
                    from_node="text",
                    from_port="text",
                    to_node="collect",
                    to_port="items",
                    to_plug="text",
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    output = next(
        run.outputs[0] for run in result.node_runs if run.node_id == "collect"
    )
    assert [
        artifacts.content(artifact.artifact_id).json()["value"]
        for artifact in output.artifacts
    ] == ["42", "answer"]


@pytest.mark.parametrize(
    ("bindings", "error_fragment"),
    [
        ([], "missing artifact type bindings: T"),
        (_binding("image.raster", schema_version=99), "unavailable artifact type"),
        (
            [
                ArtifactTypeBindingModel(
                    variable="U",
                    artifact_type=ArtifactTypeKeyResponse(
                        id="image.raster",
                        schema_version=1,
                    ),
                )
            ],
            "unknown artifact type bindings: U",
        ),
        (
            [
                ArtifactTypeBindingModel(
                    variable="U",
                    artifact_type=ArtifactTypeKeyResponse(
                        id="unavailable.type",
                        schema_version=1,
                    ),
                )
            ],
            "unknown artifact type bindings: U",
        ),
    ],
)
def test_collect_rejects_invalid_type_bindings(
    builtin_client: TestClient,
    bindings: list[ArtifactTypeBindingModel],
    error_fragment: str,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="collect",
                    operator_id="sequence.collect",
                    operator_version=1,
                    config={},
                    input_plugs=[RunInputPlugRequest(id="value", port="items")],
                    artifact_type_bindings=bindings,
                )
            ]
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert error_fragment in response.json()["detail"]


def test_run_rejects_removed_local_upload_operator(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                UnpinnedRunNodeRequest(
                    kind="builtin",
                    id="legacy-upload",
                    operator_id="source.local_upload.images",
                    operator_version=1,
                    config={},
                )
            ]
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Unknown builtin operator source.local_upload.images@1"
    )


def test_collect_rejects_removed_page_image_artifact_type(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="collect",
                    operator_id="sequence.collect",
                    operator_version=1,
                    config={},
                    input_plugs=[RunInputPlugRequest(id="image", port="items")],
                    artifact_type_bindings=_binding("source.page_image"),
                )
            ]
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert "unavailable artifact type source.page_image@1" in response.json()["detail"]


@pytest.mark.parametrize("schema_version", [True, 1.5])
def test_collect_rejects_non_integer_artifact_type_schema_versions(
    builtin_client: TestClient,
    schema_version: object,
) -> None:
    # Non-integer schema versions are rejected by the request model itself,
    # so they cannot be expressed client-side; exercise the boundary raw.
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json={
            "nodes": [
                {
                    "id": "collect",
                    "operator_id": "sequence.collect",
                    "operator_version": 1,
                    "config": {},
                    "input_plugs": [{"id": "value", "port": "items"}],
                    "artifact_type_bindings": [
                        {
                            "variable": "T",
                            "artifact_type": {
                                "id": "scalar.text",
                                "schema_version": schema_version,
                            },
                        }
                    ],
                }
            ]
        },
    )

    assert response.status_code == 422
    assert "schema_version" in str(response.json())


def test_collect_rejects_an_input_with_a_different_artifact_type(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="number",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 7},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="collect",
                    operator_id="sequence.collect",
                    operator_version=1,
                    config={},
                    input_plugs=[RunInputPlugRequest(id="number", port="items")],
                    artifact_type_bindings=_binding("image.raster"),
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="number",
                    from_port="value",
                    to_node="collect",
                    to_port="items",
                    to_plug="number",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert (
        "cannot connect scalar.integer@1 to image.raster@1" in response.json()["detail"]
    )
