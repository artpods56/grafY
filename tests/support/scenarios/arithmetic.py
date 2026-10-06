"""Arithmetic test scenario: integer math nodes used as cheap engine fixtures.

The production catalog ships no arithmetic operators; ``value.integer`` is the
only integer source users get. These nodes stay behind a ``test.arithmetic``
plugin so engine tests can still exercise multi-node graphs, mapped edges,
conversion paths, and cache policies without widening the shipped catalog.
"""

from typing import Annotated

from pydantic import Field, StrictInt

from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.artifacts import (
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.nodes import InPort, OutPort
from grafy_core.plugins import NodeCachePolicy, Plugin


ARITHMETIC_TEST_PLUGIN = Plugin(
    slug="test.arithmetic",
    title="Arithmetic test plugin",
)
ARITHMETIC_TEST_PLUGIN.register_artifact_type_dependency(INTEGER_VALUE)


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


@ARITHMETIC_TEST_PLUGIN.function_node(
    operator_id="test.arithmetic.integer_sequence",
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


@ARITHMETIC_TEST_PLUGIN.function_node(
    operator_id="test.arithmetic.add",
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


@ARITHMETIC_TEST_PLUGIN.function_node(
    operator_id="test.arithmetic.subtract",
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


@ARITHMETIC_TEST_PLUGIN.function_node(
    operator_id="test.arithmetic.multiply",
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


@ARITHMETIC_TEST_PLUGIN.function_node(
    operator_id="test.arithmetic.sum",
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


__all__ = [
    "ARITHMETIC_TEST_PLUGIN",
    "BinaryIntegerInput",
    "IntegerResultOutput",
    "IntegerSequenceConfig",
    "IntegerSequenceInput",
    "IntegerSequenceOutput",
    "SumIntegersInput",
    "SumIntegersOutput",
    "add_integers",
    "integer_sequence",
    "multiply_integers",
    "subtract_integers",
    "sum_integers",
]
