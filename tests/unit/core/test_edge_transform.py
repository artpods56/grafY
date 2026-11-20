"""A conversion that fails keeps the sentence the resolver used when it wrote."""

from pathlib import Path
from uuid import UUID

import pytest
from grafy_core.canonical_conversions import INTEGER_TO_TEXT
from grafy_core.conversions import Conversion
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.edge_transform import EdgeTransform, EdgeTransformError
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationProvenance,
)
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.artifacts import NodeInput
from grafy_core.node_context import NodeExecutionContext
from grafy_core.node_derivation import derive_input_contract
from grafy_storage import LocalFileObjectStore
from grafy_workbench.text.nodes import TEXT
from grafy_workbench.value.nodes import VALUE

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000941")
_LABEL = "Edge 'number'.'value' -> 'echo'.'text'"


class _TextInput(NodeInput):
    text: str


async def _keep(value: int) -> int:
    return value


async def _fail(value: int) -> int:
    raise RuntimeError("boom")


async def _as_text(value: int) -> str:
    return str(value)


def _chain() -> tuple[Conversion[int, int], Conversion[int, int], Conversion[int, str]]:
    integer = INTEGER_TO_TEXT.source
    text = INTEGER_TO_TEXT.target
    return (
        Conversion(
            id="test.first",
            version=1,
            title="First",
            source=integer,
            target=integer,
            convert=_keep,
        ),
        Conversion(
            id="test.second",
            version=1,
            title="Second",
            source=integer,
            target=integer,
            convert=_fail,
        ),
        Conversion(
            id="test.third",
            version=1,
            title="Third",
            source=integer,
            target=text,
            convert=_as_text,
        ),
    )


async def test_a_failing_step_reports_the_same_message(tmp_path: Path) -> None:
    values = ArtifactValues(
        (*VALUE.artifacts, *TEXT.artifacts),
        uow=InMemoryUnitOfWork(),
        storage=LocalFileObjectStore(tmp_path / "objects"),
        bucket="artifacts",
        storage_backend="local",
    )
    ref = await values.write(
        INTEGER_TO_TEXT.source.spec.key,
        4,
        ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="number",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        ),
    )
    first, second, third = _chain()
    transform = EdgeTransform(
        projection_path=None,
        conversions=(first, second, third),
        delivered=third.target.spec.key,
        label=_LABEL,
    )
    materializer = InputMaterializer(values)
    contract = derive_input_contract(_TextInput)

    with pytest.raises(EdgeTransformError) as failure:
        await materializer.materialize(
            contract,
            {"text": ref},
            WORKSPACE_ID,
            transforms={"text": (transform,)},
        )

    message = (
        f"Failed conversion step 2/3 'test.second'@1 for artifact "
        f"{ref.artifact_id} on {_LABEL}"
    )
    assert str(failure.value) == message
    assert not str(failure.value).startswith("Input ")

    with pytest.raises(EdgeTransformError) as indexed:
        await materializer.materialize(
            contract,
            {"text": ref},
            WORKSPACE_ID,
            transforms={"text": (transform,)},
            item_index=4,
        )

    assert str(indexed.value) == (
        f"Failed conversion step 2/3 'test.second'@1 for artifact "
        f"{ref.artifact_id} at sequence item 4 on {_LABEL}"
    )
