from uuid import uuid4

import pytest

from grafy_core.node_context import NodeExecutionContext, UserFacingNodeError
from grafy_core.nodes import PortShape
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_workbench.table.concat import (
    ConcatTablesConfig,
    ConcatTablesInput,
    ConcatTablesNode,
)


def test_concat_port_accepts_mapped_sequence_without_variadic_plugs() -> None:
    port = ConcatTablesNode.input_contract.ports["tables"]
    assert port.shape is PortShape.MANY
    assert port.accepted_shapes == (PortShape.MANY,)
    assert not port.variadic
    assert not port.instance_plugs


async def test_concat_stacks_tables_unifies_types_and_adds_source_index() -> None:
    first = Table(
        columns=[
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
            TableColumn(id="score", title="Score", value_type=TableValueType.INTEGER),
        ],
        rows=[{"name": "Alpha", "score": 1}],
    )
    second = Table(
        columns=[
            TableColumn(id="name", title="Name", value_type=TableValueType.TEXT),
            TableColumn(id="score", title="Score", value_type=TableValueType.NUMBER),
            TableColumn(id="note", title="Note", value_type=TableValueType.UNKNOWN),
        ],
        rows=[{"name": "Beta", "score": 0.5, "note": None}],
    )

    result = await ConcatTablesNode().run(
        NodeExecutionContext(workspace_id=uuid4()),
        ConcatTablesConfig(add_source_index=True, source_index_column="page"),
        ConcatTablesInput(tables=[first, second]),
    )

    table = result.table
    assert [(col.id, col.value_type) for col in table.columns] == [
        ("page", TableValueType.INTEGER),
        ("name", TableValueType.TEXT),
        ("score", TableValueType.NUMBER),
        ("note", TableValueType.UNKNOWN),
    ]
    assert table.rows == [
        {"page": 1, "name": "Alpha", "score": 1, "note": None},
        {"page": 2, "name": "Beta", "score": 0.5, "note": None},
    ]


async def test_concat_refuses_source_index_column_collision() -> None:
    table = Table(
        columns=[
            TableColumn(id="page", title="Page", value_type=TableValueType.INTEGER)
        ],
        rows=[{"page": 1}],
    )

    with pytest.raises(UserFacingNodeError, match="already exists"):
        await ConcatTablesNode().run(
            NodeExecutionContext(workspace_id=uuid4()),
            ConcatTablesConfig(add_source_index=True, source_index_column="page"),
            ConcatTablesInput(tables=[table]),
        )
