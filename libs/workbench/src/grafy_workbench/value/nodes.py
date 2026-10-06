from typing import Annotated, final

from pydantic import Field, StrictInt

from grafy_core.artifact_contracts import INTEGER_VALUE, IntegerValuePayload
from grafy_core.artifacts import (
    Artifact,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.ports.artifacts import UnitOfWorkPort

from grafy_workbench.scalar_persistence import ScalarOutputWriter, ScalarResolver
from grafy_workbench.value.declaration import VALUE


class IntegerConfig(NodeConfig):
    value: StrictInt = Field(description="Integer emitted by the node.")


class IntegerInput(NodeInput):
    pass


class IntegerOutput(NodeOutput):
    value: Annotated[
        StrictInt,
        OutPort(INTEGER_VALUE),
        Field(title="Value", description="The configured integer value."),
    ]


@VALUE.function_node(
    operator_id="value.integer",
    version=1,
    title="Integer",
    cache_policy=NodeCachePolicy.EXACT,
)
async def integer(config: IntegerConfig, _inputs: IntegerInput) -> IntegerOutput:
    """Produces a configured integer value."""
    return IntegerOutput(value=config.value)


@final
class IntegerValueOutputWriter(ScalarOutputWriter):
    """Keep the existing constructor used by runtime clients."""

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        super().__init__(
            artifact_type=INTEGER_VALUE.key, model=IntegerValuePayload, uow=uow
        )


@final
class IntegerValueResolver(ScalarResolver[int]):
    """Keep the existing constructor used by runtime clients."""

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        super().__init__(
            source=INTEGER_VALUE.key, target=int, model=IntegerValuePayload, uow=uow
        )


VALUE.register(
    Artifact(
        spec=INTEGER_VALUE,
        resolver=lambda context: IntegerValueResolver(uow=context.uow),
        writer=lambda context: IntegerValueOutputWriter(uow=context.uow),
    )
)
