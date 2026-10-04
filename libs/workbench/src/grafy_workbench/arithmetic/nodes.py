from typing import Annotated, final

from pydantic import Field, StrictInt

from grafy_core.artifact_contracts import INTEGER_VALUE, IntegerValuePayload
from grafy_core.artifacts import (
    Artifact,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.nodes import (
    InPort,
    OutPort,
)
from grafy_core.plugins import NodeCachePolicy

from grafy_workbench.arithmetic.declaration import ARITHMETIC
from grafy_workbench.scalar_persistence import ScalarOutputWriter, ScalarResolver


class NumberConfig(NodeConfig):
    value: StrictInt = Field(description="Integer emitted by the node.")


class NumberInput(NodeInput):
    pass


class NumberOutput(NodeOutput):
    value: Annotated[
        StrictInt,
        OutPort(INTEGER_VALUE),
        Field(title="Value", description="The configured integer value."),
    ]


@ARITHMETIC.function_node(
    operator_id="arithmetic.number",
    version=1,
    title="Number",
    cache_policy=NodeCachePolicy.EXACT,
)
async def number(config: NumberConfig, _inputs: NumberInput) -> NumberOutput:
    """Produces a configured integer value."""
    return NumberOutput(value=config.value)


class IntegerSequenceConfig(NodeConfig):
    start: StrictInt = Field(default=0, description="First integer in the sequence.")
    count: StrictInt = Field(
        default=3,
        ge=1,
        le=10_000,
        description="Number of integers to produce.",
    )
    step: StrictInt = Field(default=1, description="Difference between values.")


class IntegerSequenceInput(NodeInput):
    pass


class IntegerSequenceOutput(NodeOutput):
    values: Annotated[
        list[StrictInt],
        OutPort(INTEGER_VALUE),
        Field(title="Values", description="Ordered generated integer sequence."),
    ]


@ARITHMETIC.function_node(
    operator_id="arithmetic.integer_sequence",
    version=1,
    title="Integer sequence",
    cache_policy=NodeCachePolicy.EXACT,
)
async def integer_sequence(
    config: IntegerSequenceConfig,
    _inputs: IntegerSequenceInput,
) -> IntegerSequenceOutput:
    """Produces an ordered sequence of configured integer values."""
    return IntegerSequenceOutput(
        values=[config.start + index * config.step for index in range(config.count)]
    )


class BinaryIntegerInput(NodeInput):
    left: Annotated[
        StrictInt,
        InPort(INTEGER_VALUE),
        Field(title="Left", description="Left-hand integer operand."),
    ]
    right: Annotated[
        StrictInt,
        InPort(INTEGER_VALUE),
        Field(title="Right", description="Right-hand integer operand."),
    ]


class IntegerResultOutput(NodeOutput):
    result: Annotated[
        StrictInt,
        OutPort(INTEGER_VALUE),
        Field(description="Resulting integer value."),
    ]


@ARITHMETIC.function_node(
    operator_id="arithmetic.add",
    version=1,
    title="Add integers",
    cache_policy=NodeCachePolicy.EXACT,
)
async def add_integers(
    _config: NoConfig,
    inputs: BinaryIntegerInput,
) -> IntegerResultOutput:
    """Adds two integer inputs."""
    return IntegerResultOutput(result=inputs.left + inputs.right)


@ARITHMETIC.function_node(
    operator_id="arithmetic.subtract",
    version=1,
    title="Subtract integers",
    cache_policy=NodeCachePolicy.EXACT,
)
async def subtract_integers(
    _config: NoConfig,
    inputs: BinaryIntegerInput,
) -> IntegerResultOutput:
    """Subtracts the right integer input from the left input."""
    return IntegerResultOutput(result=inputs.left - inputs.right)


@ARITHMETIC.function_node(
    operator_id="arithmetic.multiply",
    version=1,
    title="Multiply",
    cache_policy=NodeCachePolicy.EXACT,
)
async def multiply_integers(
    _config: NoConfig,
    inputs: BinaryIntegerInput,
) -> IntegerResultOutput:
    """Multiplies two integer inputs."""
    return IntegerResultOutput(result=inputs.left * inputs.right)


class SumIntegersInput(NodeInput):
    values: Annotated[
        list[StrictInt],
        InPort(INTEGER_VALUE),
        Field(
            min_length=1,
            title="Values",
            description="Ordered integer sequence to sum.",
        ),
    ]


class SumIntegersOutput(NodeOutput):
    result: Annotated[
        StrictInt,
        OutPort(INTEGER_VALUE),
        Field(description="Sum of all input integers."),
    ]


@ARITHMETIC.function_node(
    operator_id="arithmetic.sum",
    version=1,
    title="Sum integers",
    cache_policy=NodeCachePolicy.EXACT,
)
async def sum_integers(
    _config: NoConfig,
    inputs: SumIntegersInput,
) -> SumIntegersOutput:
    """Sums an ordered integer sequence into one integer value."""
    return SumIntegersOutput(result=sum(inputs.values))


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


ARITHMETIC.register(
    Artifact(
        spec=INTEGER_VALUE,
        resolver=lambda context: IntegerValueResolver(uow=context.uow),
        writer=lambda context: IntegerValueOutputWriter(uow=context.uow),
    )
)
