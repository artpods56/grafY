import asyncio
import json
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError


from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    FieldProjectionRequest,
    PinnedOutputRequest,
    RunEdgeRequest,
    RunRequest,
    RunNodeRequest as UnpinnedRunNodeRequest,
)
from grafy_api.v1.routes.executions.models import (
    RunPortOutputResponse,
    RunResponse,
)
from tests.support.system_plugins import (
    pin_selected_system_nodes,
    selected_system_run_node as RunNodeRequest,
)
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.conversions import MAX_ARTIFACT_CONVERSION_HOPS
from grafy_workbench.arithmetic.nodes import (
    BinaryIntegerInput,
    IntegerSequenceConfig,
    IntegerSequenceOutput,
    IntegerResultOutput,
    IntegerValuePayload,
    NumberConfig,
    NumberOutput,
    SumIntegersInput,
    SumIntegersOutput,
)
from grafy_core.artifact_contracts import TEXT_VALUE

from tests.support.clients import GrafyApi


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
TEST_COMPOUND_RESULT_KEY = ArtifactTypeKey("test.compound_result", 1)


def _compound_run_request(
    *,
    left_projection: dict[str, list[str]] | None,
    right_projection: dict[str, list[str]] | None,
    number_values: tuple[object, object] = (9, 4),
) -> dict[str, object]:
    return RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="nine",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": number_values[0]},
            ),
            RunNodeRequest(
                kind="builtin",
                id="four",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": number_values[1]},
            ),
            RunNodeRequest(
                kind="builtin",
                id="compound",
                operator_id="test.compound_producer",
                operator_version=1,
                plugin_slug="test.conversion-path",
                config={},
            ),
            RunNodeRequest(
                kind="builtin",
                id="multiply",
                operator_id="arithmetic.multiply",
                operator_version=1,
                config={},
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="nine",
                from_port="value",
                to_node="compound",
                to_port="left",
            ),
            RunEdgeRequest(
                from_node="four",
                from_port="value",
                to_node="compound",
                to_port="right",
            ),
            RunEdgeRequest(
                from_node="compound",
                from_port="result",
                to_node="multiply",
                to_port="left",
                projection=(
                    FieldProjectionRequest.model_validate(left_projection)
                    if left_projection is not None
                    else None
                ),
            ),
            RunEdgeRequest(
                from_node="compound",
                from_port="result",
                to_node="multiply",
                to_port="right",
                projection=(
                    FieldProjectionRequest.model_validate(right_projection)
                    if right_projection is not None
                    else None
                ),
            ),
        ],
    ).model_dump(mode="json")


def _mapped_sum_run_request(
    *,
    collection_mode: str,
) -> dict[str, object]:
    return RunRequest(
        nodes=[
            RunNodeRequest(
                kind="builtin",
                id="sequence",
                operator_id="arithmetic.integer_sequence",
                operator_version=1,
                config={"start": 1, "count": 3, "step": 1},
            ),
            RunNodeRequest(
                kind="builtin",
                id="ten",
                operator_id="arithmetic.number",
                operator_version=1,
                config={"value": 10},
            ),
            RunNodeRequest(
                kind="builtin",
                id="multiply",
                operator_id="arithmetic.multiply",
                operator_version=1,
                config={},
            ),
            RunNodeRequest(
                kind="builtin",
                id="sum",
                operator_id="arithmetic.sum",
                operator_version=1,
                config={},
            ),
        ],
        edges=[
            RunEdgeRequest(
                from_node="sequence",
                from_port="values",
                to_node="multiply",
                to_port="left",
                collection_mode=cast(
                    Literal["direct", "map"],
                    collection_mode,
                ),
            ),
            RunEdgeRequest(
                from_node="ten",
                from_port="value",
                to_node="multiply",
                to_port="right",
            ),
            RunEdgeRequest(
                from_node="multiply",
                from_port="result",
                to_node="sum",
                to_port="values",
            ),
        ],
    ).model_dump(mode="json")


def _run_output(
    result: RunResponse,
    node_id: str,
    port: str,
) -> RunPortOutputResponse:
    node_run = next(run for run in result.node_runs if run.node_id == node_id)
    return next(output for output in node_run.outputs if output.port == port)


async def _stored_artifacts(
    uow: InMemoryUnitOfWork,
    key: ArtifactTypeKey,
) -> list[ArtifactObject]:
    async with uow as entered:
        return await entered.artifacts.list_by_type(WORKSPACE_ID, key)


def test_registry_declares_scalar_arithmetic_nodes_and_test_compound_projections(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, _uow = conversion_path_client
    response = client.get("/v1/workspaces/00000000-0000-0000-0000-000000000007/nodes")

    assert response.status_code == 200
    registry = NodeRegistryResponse.model_validate(response.json())
    artifact_types = {
        artifact_type.key.id: artifact_type for artifact_type in registry.artifact_types
    }
    assert "arithmetic.result" not in artifact_types
    assert artifact_types["scalar.integer"].field_projections == []

    result_type = artifact_types["test.compound_result"]
    assert [
        projection.model_dump() for projection in result_type.field_projections
    ] == [
        {
            "path": ["addition"],
            "target_artifact_type": {
                "id": "scalar.integer",
                "schema_version": 1,
            },
            "title": "Addition",
        },
        {
            "path": ["subtraction"],
            "target_artifact_type": {
                "id": "scalar.integer",
                "schema_version": 1,
            },
            "title": "Subtraction",
        },
    ]

    nodes = {node.operator_id: node for node in registry.nodes}
    assert [
        (nodes[operator_id].title, nodes[operator_id].plugin_slug)
        for operator_id in (
            "arithmetic.number",
            "arithmetic.add",
            "arithmetic.subtract",
            "arithmetic.multiply",
        )
    ] == [
        ("Number", "arithmetic"),
        ("Add integers", "arithmetic"),
        ("Subtract integers", "arithmetic"),
        ("Multiply", "arithmetic"),
    ]


def test_integer_output_converts_to_text_before_text_node_execution(
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
                    config={"value": 9},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="replace",
                    operator_id="text.replace",
                    operator_version=1,
                    config={"search": "9", "replacement": "nine"},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="number",
                    from_port="value",
                    to_node="replace",
                    to_port="text",
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        )
                    ],
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    replaced = _run_output(result, "replace", "text")
    assert replaced.kind == "single"
    assert replaced.artifacts[0].artifact_type == "scalar.text"
    replaced_content = artifacts.content(replaced.artifacts[0].artifact_id)
    assert replaced_content.status_code == 200
    assert replaced_content.json() == {"value": "nine"}

    provenance = cast(
        dict[str, list[dict[str, object]]],
        replaced.artifacts[0].metadata["provenance"],
    )
    assert isinstance(provenance, dict)
    converted_refs = provenance["text"]
    assert isinstance(converted_refs, list)
    converted_ref = converted_refs[0]
    assert isinstance(converted_ref, dict)
    converted_content = artifacts.content(converted_ref["artifact_id"])
    assert converted_content.status_code == 200
    assert converted_content.json() == {"value": "9"}


def test_projection_runs_before_declared_integer_to_text_conversion(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, _uow = conversion_path_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="nine",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 9},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="four",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 4},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="compound",
                    operator_id="test.compound_producer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="replace",
                    operator_id="text.replace",
                    operator_version=1,
                    config={"search": "13", "replacement": "thirteen"},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="nine",
                    from_port="value",
                    to_node="compound",
                    to_port="left",
                ),
                RunEdgeRequest(
                    from_node="four",
                    from_port="value",
                    to_node="compound",
                    to_port="right",
                ),
                RunEdgeRequest(
                    from_node="compound",
                    from_port="result",
                    to_node="replace",
                    to_port="text",
                    projection=FieldProjectionRequest(path=["addition"]),
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        )
                    ],
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    replaced = _run_output(result, "replace", "text")
    replaced_content = artifacts.content(replaced.artifacts[0].artifact_id)
    assert replaced_content.status_code == 200
    assert replaced_content.json() == {"value": "thirteen"}


def test_integer_sequence_conversion_preserves_order_through_mapped_text_node(
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
                    id="sequence",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 1, "count": 3, "step": 1},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="replace",
                    operator_id="text.replace",
                    operator_version=1,
                    config={"search": "2", "replacement": "two"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="join",
                    operator_id="text.join",
                    operator_version=1,
                    config={"separator": ","},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="sequence",
                    from_port="values",
                    to_node="replace",
                    to_port="text",
                    collection_mode="map",
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        )
                    ],
                ),
                RunEdgeRequest(
                    from_node="replace",
                    from_port="text",
                    to_node="join",
                    to_port="parts",
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    replaced = _run_output(result, "replace", "text")
    assert isinstance(replaced.value, ArtifactRefSequence)
    assert replaced.value.ordered is True
    assert replaced.value.index_key == "order_index"
    assert [
        artifacts.content(artifact.artifact_id).json()["value"]
        for artifact in replaced.artifacts
    ] == ["1", "two", "3"]
    joined = _run_output(result, "join", "text").artifacts[0]
    joined_content = artifacts.content(joined.artifact_id)
    assert joined_content.status_code == 200
    assert joined_content.json() == {"value": "1,two,3"}


def test_transitive_conversion_path_composes_in_memory_and_writes_final_only(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, uow = conversion_path_client
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="number",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 9},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="consumer",
                    operator_id="test.compound_result_consumer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="number",
                    from_port="value",
                    to_node="consumer",
                    to_port="result",
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        ),
                        ArtifactConversionRequest(
                            id="test.scalar.text_to_compound_result",
                            version=1,
                        ),
                    ],
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    assert _run_output(result, "consumer", "value").artifacts[0].text == "80"
    assert asyncio.run(_stored_artifacts(uow, TEXT_VALUE.key)) == []
    final_artifacts = asyncio.run(_stored_artifacts(uow, TEST_COMPOUND_RESULT_KEY))
    assert len(final_artifacts) == 1
    assert final_artifacts[0].inline_payload == {"addition": 10, "subtraction": 8}
    assert final_artifacts[0].metadata["conversion_path"] == [
        {"id": "builtin.scalar.integer_to_text", "version": 1},
        {"id": "test.scalar.text_to_compound_result", "version": 1},
    ]


def test_projection_runs_before_every_step_in_a_transitive_conversion_path(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, uow = conversion_path_client
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="nine",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 9},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="four",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 4},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="compound",
                    operator_id="test.compound_producer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="consumer",
                    operator_id="test.compound_result_consumer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="nine",
                    from_port="value",
                    to_node="compound",
                    to_port="left",
                ),
                RunEdgeRequest(
                    from_node="four",
                    from_port="value",
                    to_node="compound",
                    to_port="right",
                ),
                RunEdgeRequest(
                    from_node="compound",
                    from_port="result",
                    to_node="consumer",
                    to_port="result",
                    projection=FieldProjectionRequest(path=["addition"]),
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        ),
                        ArtifactConversionRequest(
                            id="test.scalar.text_to_compound_result",
                            version=1,
                        ),
                    ],
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    assert _run_output(result, "consumer", "value").artifacts[0].text == "168"
    assert asyncio.run(_stored_artifacts(uow, TEXT_VALUE.key)) == []
    final_artifacts = asyncio.run(_stored_artifacts(uow, TEST_COMPOUND_RESULT_KEY))
    assert len(final_artifacts) == 2
    converted = next(
        artifact
        for artifact in final_artifacts
        if "conversion_path" in artifact.metadata
    )
    assert converted.inline_payload == {"addition": 14, "subtraction": 12}


def test_sequence_items_each_traverse_the_full_conversion_path_before_mapping(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, uow = conversion_path_client
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="sequence",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 1, "count": 3, "step": 1},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="consumer",
                    operator_id="test.compound_result_consumer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="sequence",
                    from_port="values",
                    to_node="consumer",
                    to_port="result",
                    collection_mode="map",
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        ),
                        ArtifactConversionRequest(
                            id="test.scalar.text_to_compound_result",
                            version=1,
                        ),
                    ],
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    output = _run_output(result, "consumer", "value")
    assert output.kind == "sequence"
    assert [artifact.text for artifact in output.artifacts] == ["0", "3", "8"]
    assert asyncio.run(_stored_artifacts(uow, TEXT_VALUE.key)) == []
    assert len(asyncio.run(_stored_artifacts(uow, TEST_COMPOUND_RESULT_KEY))) == 3


@pytest.mark.parametrize(
    ("conversion_path", "error_fragment"),
    [
        (
            [
                {"id": "builtin.scalar.integer_to_text", "version": 1},
                {"id": "missing.text_to_result", "version": 1},
            ],
            "requests undeclared conversion 'missing.text_to_result'@1 at step 2",
        ),
        (
            [
                {"id": "builtin.scalar.integer_to_text", "version": 1},
                {"id": "builtin.scalar.integer_to_text", "version": 1},
            ],
            "applies conversion step 2",
        ),
        (
            [{"id": "builtin.scalar.integer_to_text", "version": 1}],
            "as scalar.text@1, but target expects test.compound_result@1",
        ),
        (
            [
                {"id": "builtin.scalar.integer_to_text", "version": 1},
                {"id": "test.scalar.text_to_integer", "version": 1},
            ],
            "conversion path repeats artifact type scalar.integer@1 at step 2",
        ),
    ],
)
def test_invalid_conversion_paths_are_rejected_before_node_execution(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
    conversion_path: list[dict[str, object]],
    error_fragment: str,
) -> None:
    client, _uow = conversion_path_client
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="invalid-number",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": "would-fail-if-executed"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="consumer",
                    operator_id="test.compound_result_consumer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="invalid-number",
                    from_port="value",
                    to_node="consumer",
                    to_port="result",
                    conversion_path=[
                        ArtifactConversionRequest.model_validate(item)
                        for item in conversion_path
                    ],
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert error_fragment in response.json()["detail"]


@pytest.mark.parametrize(
    "failing_conversion",
    [
        "test.scalar.text_to_compound_result_failure",
        "test.scalar.text_to_invalid_compound_result",
    ],
)
def test_conversion_path_errors_identify_the_exact_failing_step(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
    failing_conversion: str,
) -> None:
    client, uow = conversion_path_client
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="number",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 9},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="consumer",
                    operator_id="test.compound_result_consumer",
                    operator_version=1,
                    plugin_slug="test.conversion-path",
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="number",
                    from_port="value",
                    to_node="consumer",
                    to_port="result",
                    conversion_path=[
                        ArtifactConversionRequest(
                            id="builtin.scalar.integer_to_text",
                            version=1,
                        ),
                        ArtifactConversionRequest(
                            id=failing_conversion,
                            version=1,
                        ),
                    ],
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    consumer_run = next(run for run in result.node_runs if run.node_id == "consumer")
    assert consumer_run.status == "failed"
    assert consumer_run.error is not None
    assert "Failed conversion step 2/2" in consumer_run.error
    assert f"{failing_conversion!r}@1" in consumer_run.error
    assert asyncio.run(_stored_artifacts(uow, TEXT_VALUE.key)) == []
    assert asyncio.run(_stored_artifacts(uow, TEST_COMPOUND_RESULT_KEY)) == []


@pytest.mark.parametrize(
    ("nodes", "edge", "error_fragment"),
    cast(
        list[tuple[list[dict[str, object]], dict[str, object], str]],
        [
            (
                [
                    {
                        "kind": "builtin",
                        "id": "source",
                        "operator_id": "arithmetic.number",
                        "operator_version": 1,
                        "config": {"value": "not-an-integer"},
                    },
                    {
                        "kind": "builtin",
                        "id": "target",
                        "operator_id": "text.replace",
                        "operator_version": 1,
                        "config": {"search": "x", "replacement": "y"},
                    },
                ],
                {
                    "from_node": "source",
                    "from_port": "value",
                    "to_node": "target",
                    "to_port": "text",
                    "conversion": {
                        "id": "missing.integer_to_text",
                        "version": 1,
                    },
                },
                "requests undeclared conversion 'missing.integer_to_text'@1",
            ),
            (
                [
                    {
                        "kind": "builtin",
                        "id": "source",
                        "operator_id": "text.input",
                        "operator_version": 1,
                        "config": {"text": 123},
                    },
                    {
                        "kind": "builtin",
                        "id": "target",
                        "operator_id": "text.replace",
                        "operator_version": 1,
                        "config": {"search": "x", "replacement": "y"},
                    },
                ],
                {
                    "from_node": "source",
                    "from_port": "text",
                    "to_node": "target",
                    "to_port": "text",
                    "conversion": {
                        "id": "builtin.scalar.integer_to_text",
                        "version": 1,
                    },
                },
                "expects scalar.integer@1, to scalar.text@1",
            ),
            (
                [
                    {
                        "kind": "builtin",
                        "id": "source",
                        "operator_id": "arithmetic.integer_sequence",
                        "operator_version": 1,
                        "config": {"start": "not-an-integer", "count": 3},
                    },
                    {
                        "kind": "builtin",
                        "id": "target",
                        "operator_id": "arithmetic.sum",
                        "operator_version": 1,
                        "config": {},
                    },
                ],
                {
                    "from_node": "source",
                    "from_port": "values",
                    "to_node": "target",
                    "to_port": "values",
                    "conversion": {
                        "id": "builtin.scalar.integer_to_text",
                        "version": 1,
                    },
                },
                "as scalar.text@1, but target expects scalar.integer@1",
            ),
        ],
    ),
)
def test_invalid_conversion_is_422_before_node_execution(
    builtin_client: TestClient,
    nodes: list[dict[str, object]],
    edge: dict[str, object],
    error_fragment: str,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=pin_selected_system_nodes(
                [UnpinnedRunNodeRequest.model_validate(node) for node in nodes]
            ),
            edges=[RunEdgeRequest.model_validate(edge)],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert error_fragment in response.json()["detail"]


def test_add_and_subtract_nodes_feed_scalar_results_into_multiply(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="nine",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 9},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="four",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 4},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="add",
                    operator_id="arithmetic.add",
                    operator_version=1,
                    config={},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="subtract",
                    operator_id="arithmetic.subtract",
                    operator_version=1,
                    config={},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="nine",
                    from_port="value",
                    to_node="add",
                    to_port="left",
                ),
                RunEdgeRequest(
                    from_node="four",
                    from_port="value",
                    to_node="add",
                    to_port="right",
                ),
                RunEdgeRequest(
                    from_node="nine",
                    from_port="value",
                    to_node="subtract",
                    to_port="left",
                ),
                RunEdgeRequest(
                    from_node="four",
                    from_port="value",
                    to_node="subtract",
                    to_port="right",
                ),
                RunEdgeRequest(
                    from_node="add",
                    from_port="result",
                    to_node="multiply",
                    to_port="left",
                ),
                RunEdgeRequest(
                    from_node="subtract",
                    from_port="result",
                    to_node="multiply",
                    to_port="right",
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert _run_output(result, "add", "result").artifacts[0].text == "13"
    assert _run_output(result, "subtract", "result").artifacts[0].text == "5"
    assert _run_output(result, "multiply", "result").artifacts[0].text == "65"


def test_test_compound_graph_projects_both_result_fields_into_multiply(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, _uow = conversion_path_client
    api = GrafyApi(client)
    artifacts = api.workspace(WORKSPACE_ID).artifacts
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_compound_run_request(
            left_projection={"path": ["addition"]},
            right_projection={"path": ["subtraction"]},
        ),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    runs = {run.node_id: run for run in result.node_runs}
    assert all(run.status == "succeeded" for run in runs.values())
    assert runs["nine"].outputs[0].artifacts[0].text == "9"
    assert runs["four"].outputs[0].artifacts[0].text == "4"

    compound = runs["compound"].outputs[0].artifacts[0]
    assert compound.artifact_type == "test.compound_result"
    assert json.loads(compound.text or "") == {
        "addition": 13,
        "subtraction": 5,
    }
    compound_content = artifacts.content(compound.artifact_id)
    assert compound_content.status_code == 200
    assert compound_content.json() == {"addition": 13, "subtraction": 5}

    product = runs["multiply"].outputs[0].artifacts[0]
    assert product.artifact_type == "scalar.integer"
    assert product.text == "65"
    product_content = artifacts.content(product.artifact_id)
    assert product_content.status_code == 200
    assert product_content.json() == {"value": 65}


def test_selected_target_projects_two_edges_from_one_pinned_compound_output(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
) -> None:
    client, _uow = conversion_path_client
    upstream_response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_compound_run_request(
            left_projection={"path": ["addition"]},
            right_projection={"path": ["subtraction"]},
        ),
    )
    assert upstream_response.status_code == 200
    upstream_result = RunResponse.model_validate(upstream_response.json())
    compound_output = _run_output(upstream_result, "compound", "result")
    assert isinstance(compound_output.value, ArtifactRef)
    assert compound_output.value.artifact_id == compound_output.artifacts[0].artifact_id
    assert compound_output.value.content_hash == compound_output.artifacts[0].sha256

    selected_response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                )
            ],
            edges=[
                RunEdgeRequest(
                    from_node="compound",
                    from_port="result",
                    to_node="multiply",
                    to_port="left",
                    projection=FieldProjectionRequest(path=["addition"]),
                ),
                RunEdgeRequest(
                    from_node="compound",
                    from_port="result",
                    to_node="multiply",
                    to_port="right",
                    projection=FieldProjectionRequest(path=["subtraction"]),
                ),
            ],
            pinned_outputs=[
                PinnedOutputRequest(
                    from_node="compound",
                    from_port="result",
                    value=compound_output.value,
                )
            ],
        ).model_dump(mode="json"),
    )

    assert selected_response.status_code == 200
    selected_result = RunResponse.model_validate(selected_response.json())
    assert selected_result.status == "succeeded"
    assert [run.node_id for run in selected_result.node_runs] == ["multiply"]
    product_output = _run_output(selected_result, "multiply", "result")
    assert isinstance(product_output.value, ArtifactRef)
    assert product_output.value.artifact_id == product_output.artifacts[0].artifact_id
    assert product_output.value.content_hash == product_output.artifacts[0].sha256
    assert product_output.artifacts[0].text == "65"


def test_integer_sequence_maps_multiply_and_sums_once(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_mapped_sum_run_request(collection_mode="map"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    runs = {run.node_id: run for run in result.node_runs}
    assert [artifact.text for artifact in runs["sequence"].outputs[0].artifacts] == [
        "1",
        "2",
        "3",
    ]
    assert runs["multiply"].outputs[0].kind == "sequence"
    assert [artifact.text for artifact in runs["multiply"].outputs[0].artifacts] == [
        "10",
        "20",
        "30",
    ]
    assert runs["sum"].outputs[0].kind == "single"
    assert runs["sum"].outputs[0].artifacts[0].text == "60"


def test_selected_mapped_run_uses_exact_pinned_sequence_envelope_in_order(
    builtin_client: TestClient,
) -> None:
    upstream_response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="sequence",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 1, "count": 3, "step": 1},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="ten",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 10},
                ),
            ],
            edges=[],
        ).model_dump(mode="json"),
    )
    assert upstream_response.status_code == 200
    upstream_result = RunResponse.model_validate(upstream_response.json())
    sequence_output = _run_output(upstream_result, "sequence", "values")
    ten_output = _run_output(upstream_result, "ten", "value")
    assert isinstance(sequence_output.value, ArtifactRefSequence)
    assert isinstance(ten_output.value, ArtifactRef)
    assert [ref.artifact_id for ref in sequence_output.value.item_refs] == [
        artifact.artifact_id for artifact in sequence_output.artifacts
    ]

    selected_response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                )
            ],
            edges=[
                RunEdgeRequest(
                    from_node="sequence",
                    from_port="values",
                    to_node="multiply",
                    to_port="left",
                    collection_mode="map",
                ),
                RunEdgeRequest(
                    from_node="ten",
                    from_port="value",
                    to_node="multiply",
                    to_port="right",
                ),
            ],
            pinned_outputs=[
                PinnedOutputRequest(
                    from_node="sequence",
                    from_port="values",
                    value=sequence_output.value,
                ),
                PinnedOutputRequest(
                    from_node="ten",
                    from_port="value",
                    value=ten_output.value,
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert selected_response.status_code == 200
    selected_result = RunResponse.model_validate(selected_response.json())
    multiplied_output = _run_output(selected_result, "multiply", "result")
    assert isinstance(multiplied_output.value, ArtifactRefSequence)
    assert [artifact.text for artifact in multiplied_output.artifacts] == [
        "10",
        "20",
        "30",
    ]
    assert multiplied_output.value.ordered is sequence_output.value.ordered
    assert multiplied_output.value.index_key == sequence_output.value.index_key
    assert multiplied_output.value.metadata["source_sequence_id"] == str(
        sequence_output.value.sequence_id
    )


def test_selected_run_uses_submitted_older_or_newer_pin_without_latest_lookup(
    builtin_client: TestClient,
) -> None:
    pinned_values: list[ArtifactRef] = []
    for value in (3, 7):
        response = builtin_client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="source",
                        operator_id="arithmetic.number",
                        operator_version=1,
                        config={"value": value},
                    )
                ],
                edges=[],
            ).model_dump(mode="json"),
        )
        assert response.status_code == 200
        result = RunResponse.model_validate(response.json())
        output_value = _run_output(result, "source", "value").value
        assert isinstance(output_value, ArtifactRef)
        pinned_values.append(output_value)
    assert pinned_values[0].artifact_id != pinned_values[1].artifact_id

    products: list[str | None] = []
    for pinned_value in pinned_values:
        response = builtin_client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json=RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="multiply",
                        operator_id="arithmetic.multiply",
                        operator_version=1,
                        config={},
                    )
                ],
                edges=[
                    RunEdgeRequest(
                        from_node="source",
                        from_port="value",
                        to_node="multiply",
                        to_port="left",
                    ),
                    RunEdgeRequest(
                        from_node="source",
                        from_port="value",
                        to_node="multiply",
                        to_port="right",
                    ),
                ],
                pinned_outputs=[
                    PinnedOutputRequest(
                        from_node="source",
                        from_port="value",
                        value=pinned_value,
                    )
                ],
            ).model_dump(mode="json"),
        )
        assert response.status_code == 200
        result = RunResponse.model_validate(response.json())
        products.append(_run_output(result, "multiply", "result").artifacts[0].text)

    assert products == ["9", "49"]


@pytest.mark.parametrize(
    ("case", "error_fragment"),
    [
        ("missing-artifact", "references missing artifact"),
        ("mismatched-ref", "does not match the repository ref for artifact"),
        ("missing-pin", "requires a pinned output"),
        ("duplicate-pin", "Duplicate pinned output"),
        ("unused-pin", "is not used by any incoming edge"),
        (
            "wrong-artifact-type",
            "cannot connect test.compound_result@1 to scalar.integer@1",
        ),
    ],
)
def test_invalid_selected_run_pins_are_rejected_before_target_execution(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
    case: str,
    error_fragment: str,
) -> None:
    client, _uow = conversion_path_client
    upstream_response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_compound_run_request(
            left_projection={"path": ["addition"]},
            right_projection={"path": ["subtraction"]},
        ),
    )
    assert upstream_response.status_code == 200
    upstream_result = RunResponse.model_validate(upstream_response.json())
    integer_value = _run_output(upstream_result, "nine", "value").value
    compound_value = _run_output(upstream_result, "compound", "result").value
    assert isinstance(integer_value, ArtifactRef)
    assert isinstance(compound_value, ArtifactRef)

    edges: list[dict[str, object]] = [
        RunEdgeRequest(
            from_node="source",
            from_port="value",
            to_node="multiply",
            to_port="left",
        ).model_dump(mode="json"),
        RunEdgeRequest(
            from_node="source",
            from_port="value",
            to_node="multiply",
            to_port="right",
        ).model_dump(mode="json"),
    ]
    pinned_outputs: list[dict[str, object]] = [
        PinnedOutputRequest(
            from_node="source",
            from_port="value",
            value=integer_value,
        ).model_dump(mode="json"),
    ]
    if case == "missing-artifact":
        missing_value = integer_value.model_copy(
            update={"artifact_id": uuid4()},
        )
        pinned_outputs[0]["value"] = missing_value.model_dump(mode="json")
    elif case == "mismatched-ref":
        mismatched_value = integer_value.model_copy(
            update={"content_hash": "not-the-repository-hash"},
        )
        pinned_outputs[0]["value"] = mismatched_value.model_dump(mode="json")
    elif case == "missing-pin":
        pinned_outputs = []
    elif case == "duplicate-pin":
        pinned_outputs.append(dict(pinned_outputs[0]))
    elif case == "unused-pin":
        pinned_outputs.append(
            PinnedOutputRequest(
                from_node="unused",
                from_port="value",
                value=integer_value,
            ).model_dump(mode="json")
        )
    elif case == "wrong-artifact-type":
        edges = [
            RunEdgeRequest(
                from_node="source",
                from_port="result",
                to_node="multiply",
                to_port="left",
            ).model_dump(mode="json"),
            RunEdgeRequest(
                from_node="source",
                from_port="result",
                to_node="multiply",
                to_port="right",
            ).model_dump(mode="json"),
        ]
        pinned_outputs = [
            PinnedOutputRequest(
                from_node="source",
                from_port="result",
                value=compound_value,
            ).model_dump(mode="json"),
        ]

    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                )
            ],
            edges=[RunEdgeRequest.model_validate(edge) for edge in edges],
            pinned_outputs=[
                PinnedOutputRequest.model_validate(pin) for pin in pinned_outputs
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert error_fragment in response.json()["detail"]


def test_pin_for_executing_source_is_rejected_before_source_config_runs(
    builtin_client: TestClient,
) -> None:
    upstream_response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": 3},
                )
            ],
            edges=[],
        ).model_dump(mode="json"),
    )
    assert upstream_response.status_code == 200
    upstream_result = RunResponse.model_validate(upstream_response.json())
    pinned_value = _run_output(upstream_result, "source", "value").value
    assert isinstance(pinned_value, ArtifactRef)

    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="source",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": "invalid"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="value",
                    to_node="multiply",
                    to_port="left",
                ),
                RunEdgeRequest(
                    from_node="source",
                    from_port="value",
                    to_node="multiply",
                    to_port="right",
                ),
            ],
            pinned_outputs=[
                PinnedOutputRequest(
                    from_node="source",
                    from_port="value",
                    value=pinned_value,
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Pinned output 'source'.'value' is invalid because source node "
        "'source' is also being executed"
    )


def test_crossing_edge_to_unknown_target_is_rejected(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[],
            edges=[
                RunEdgeRequest(
                    from_node="source",
                    from_port="value",
                    to_node="missing-target",
                    to_port="left",
                )
            ],
            pinned_outputs=[],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert (
        "references unknown target node 'missing-target'" in response.json()["detail"]
    )


def test_many_output_cannot_feed_once_item_input(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_mapped_sum_run_request(collection_mode="direct"),
    )

    assert response.status_code == 422
    assert "incompatible shapes" in response.json()["detail"]
    assert "source is 'many', target expects 'one'" in response.json()["detail"]


def test_invalid_map_edge_target_is_rejected_before_execution(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="sequence",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 1, "count": 3, "step": 1},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="sequence",
                    from_port="values",
                    to_node="multiply",
                    to_port="missing",
                    collection_mode="map",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert "cannot drive mapped execution" in response.json()["detail"]
    assert "missing" in response.json()["detail"]


def test_node_rejects_more_than_one_map_edge(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="left-sequence",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 1, "count": 2, "step": 1},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="right-sequence",
                    operator_id="arithmetic.integer_sequence",
                    operator_version=1,
                    config={"start": 3, "count": 2, "step": 1},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="multiply",
                    operator_id="arithmetic.multiply",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="left-sequence",
                    from_port="values",
                    to_node="multiply",
                    to_port="left",
                    collection_mode="map",
                ),
                RunEdgeRequest(
                    from_node="right-sequence",
                    from_port="values",
                    to_node="multiply",
                    to_port="right",
                    collection_mode="map",
                ),
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert "more than one map edge" in response.json()["detail"]
    assert "exactly one edge may drive mapped execution" in response.json()["detail"]


def test_unknown_operator_version_is_rejected_before_execution(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                UnpinnedRunNodeRequest(
                    kind="builtin",
                    id="number",
                    operator_id="arithmetic.number",
                    operator_version=99,
                    config={"value": "not-an-integer"},
                )
            ],
            edges=[],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown builtin operator arithmetic.number@99"


@pytest.mark.parametrize(
    ("projection", "error_fragment"),
    [
        (None, "without a declared field projection"),
        ({"path": ["missing"]}, "requests undeclared projection 'missing'"),
    ],
)
def test_invalid_test_compound_projection_is_422_before_node_execution(
    conversion_path_client: tuple[TestClient, InMemoryUnitOfWork],
    projection: dict[str, list[str]] | None,
    error_fragment: str,
) -> None:
    client, _uow = conversion_path_client
    response = client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=_compound_run_request(
            left_projection=projection,
            right_projection={"path": ["subtraction"]},
            number_values=("not-an-integer", "also-not-an-integer"),
        ),
    )

    assert response.status_code == 422
    assert error_fragment in response.json()["detail"]


def test_missing_required_arithmetic_input_is_422_before_node_execution(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json=RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="invalid-number",
                    operator_id="arithmetic.number",
                    operator_version=1,
                    config={"value": "not-an-integer"},
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="add",
                    operator_id="arithmetic.add",
                    operator_version=1,
                    config={},
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="invalid-number",
                    from_port="value",
                    to_node="add",
                    to_port="left",
                )
            ],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Node 'add' (arithmetic.add@1) required input 'right' has no incoming edge"
    )


@pytest.mark.parametrize("value", [True, "9"])
def test_number_node_config_does_not_coerce_non_integer_values(
    builtin_client: TestClient,
    value: object,
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
                    config={"value": value},
                )
            ],
            edges=[],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "failed"
    assert len(result.node_runs) == 1
    node_run = result.node_runs[0]
    assert node_run.status == "failed"
    assert node_run.outputs == []
    assert node_run.error is not None
    assert "Input should be a valid integer" in node_run.error


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (NumberConfig, {"value": True}),
        (NumberConfig, {"value": "9"}),
        (NumberOutput, {"value": True}),
        (NumberOutput, {"value": "9"}),
        (IntegerValuePayload, {"value": True}),
        (IntegerValuePayload, {"value": "9"}),
        (BinaryIntegerInput, {"left": True, "right": 4}),
        (BinaryIntegerInput, {"left": 9, "right": "4"}),
        (IntegerResultOutput, {"result": True}),
        (IntegerResultOutput, {"result": "36"}),
        (IntegerSequenceConfig, {"start": True, "count": 3, "step": 1}),
        (IntegerSequenceConfig, {"start": 0, "count": "3", "step": 1}),
        (IntegerSequenceConfig, {"start": 0, "count": 3, "step": False}),
        (IntegerSequenceOutput, {"values": [1, "2", 3]}),
        (SumIntegersInput, {"values": [1, False, 3]}),
        (SumIntegersOutput, {"result": "6"}),
    ],
)
def test_arithmetic_models_reject_bool_and_string_integers(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Input should be a valid integer"):
        model.model_validate(payload)


@pytest.mark.parametrize("count", [0, 10_001])
def test_integer_sequence_count_is_bounded(count: int) -> None:
    with pytest.raises(ValidationError):
        IntegerSequenceConfig(count=count)


def test_sum_integers_requires_at_least_one_value() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        SumIntegersInput(values=[])


def test_edge_collection_mode_is_narrow() -> None:
    with pytest.raises(ValidationError):
        RunEdgeRequest.model_validate(
            {
                "from_node": "source",
                "from_port": "values",
                "to_node": "target",
                "to_port": "value",
                "collection_mode": "broadcast",
            }
        )


@pytest.mark.parametrize(
    "conversion",
    [
        {"id": "   ", "version": 1},
        {"id": "builtin.scalar.integer_to_text", "version": 0},
    ],
)
def test_edge_conversion_identity_is_narrow(
    conversion: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunEdgeRequest.model_validate(
            {
                "from_node": "source",
                "from_port": "value",
                "to_node": "target",
                "to_port": "text",
                "conversion": conversion,
            }
        )


def test_run_edge_normalizes_legacy_conversion_and_rejects_ambiguous_fields() -> None:
    legacy = RunEdgeRequest.model_validate(
        {
            "from_node": "source",
            "from_port": "value",
            "to_node": "target",
            "to_port": "text",
            "conversion": {
                "id": "builtin.scalar.integer_to_text",
                "version": 1,
            },
        }
    )

    assert [step.model_dump() for step in legacy.conversion_path] == [
        {"id": "builtin.scalar.integer_to_text", "version": 1}
    ]
    assert "conversion" not in legacy.model_dump(mode="json")

    with pytest.raises(ValidationError, match="both conversion and conversion_path"):
        RunEdgeRequest.model_validate(
            {
                **legacy.model_dump(mode="json"),
                "conversion": {
                    "id": "builtin.scalar.integer_to_text",
                    "version": 1,
                },
            }
        )


def test_run_edge_conversion_path_has_a_bounded_hop_count() -> None:
    with pytest.raises(ValidationError, match="at most 8 items"):
        RunEdgeRequest.model_validate(
            {
                "from_node": "source",
                "from_port": "value",
                "to_node": "target",
                "to_port": "text",
                "conversion_path": [
                    {"id": f"test.conversion.{index}", "version": 1}
                    for index in range(MAX_ARTIFACT_CONVERSION_HOPS + 1)
                ],
            }
        )
