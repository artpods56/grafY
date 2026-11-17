from typing import Annotated

from pydantic import Field, StrictInt

from grafy_core.artifact_contracts import INTEGER_VALUE, IntegerValuePayload
from grafy_core.artifacts import (
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import OutPort
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.artifact_values import scalar_artifact

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


VALUE.register(scalar_artifact(INTEGER_VALUE, int, IntegerValuePayload))
