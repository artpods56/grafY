import json
from hashlib import sha256
from typing import Annotated, cast, final, override
from uuid import UUID

from pydantic import Field, StrictInt, ValidationError

from grafy_core.artifact_contracts import INTEGER_VALUE, IntegerValuePayload
from grafy_core.domain.errors import NotFoundError
from grafy_core.artifacts import (
    Artifact,
    ArtifactObject,
    ArtifactRef,
    JsonObject,
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
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
)
from grafy_core.runtime.resolvers import (
    ArtifactContractError,
    ResolutionError,
    Resolver,
)

from grafy_workbench.arithmetic.declaration import ARITHMETIC


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
class IntegerValueOutputWriter(ArtifactOutputWriter):
    artifact_type = INTEGER_VALUE.key

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        try:
            payload = IntegerValuePayload.model_validate({"value": value})
        except ValidationError as exc:
            message = (
                f"Failed to serialize {self.artifact_type.id}@"
                f"{self.artifact_type.schema_version} value produced by node "
                f"{context.node_context.node_id!r}"
            )
            raise RuntimeError(message) from exc

        payload_json = cast(JsonObject, payload.model_dump(mode="json"))
        payload_bytes = json.dumps(
            payload_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        provenance: dict[str, object] = {
            input_name: [
                {
                    "artifact_id": str(ref.artifact_id),
                    "artifact_type": ref.artifact_type,
                    "schema_version": ref.schema_version,
                }
                for ref in refs
            ]
            for input_name, refs in context.provenance.refs_by_input.items()
        }
        metadata: JsonObject = {
            "producer_node_id": context.node_context.node_id,
        }
        if provenance:
            metadata["provenance"] = provenance
        metadata.update(context.metadata)
        artifact = ArtifactObject(
            workspace_id=context.node_context.workspace_id,
            artifact_type=self.artifact_type.id,
            schema_version=self.artifact_type.schema_version,
            content_type="application/json",
            storage_backend="inline",
            inline_payload=payload_json,
            byte_size=len(payload_bytes),
            sha256=sha256(payload_bytes).hexdigest(),
            metadata=metadata,
        )
        try:
            async with self._uow as uow:
                await uow.artifacts.add(artifact)
                await uow.commit()
        except Exception as exc:
            message = (
                f"Failed to persist {self.artifact_type.id}@"
                f"{self.artifact_type.schema_version} produced by node "
                f"{context.node_context.node_id!r}"
            )
            raise RuntimeError(message) from exc
        return artifact.ref()


@final
class IntegerValueResolver(Resolver[int]):
    source = INTEGER_VALUE.key
    target: type[object] = int

    def __init__(self, *, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    @override
    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> int:
        if ref.key() != self.source:
            message = (
                f"Integer resolver expected {self.source.id}@"
                f"{self.source.schema_version}, got {ref.artifact_type}@"
                f"{ref.schema_version} for artifact {ref.artifact_id}"
            )
            raise ArtifactContractError(message)

        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, ref.artifact_id)
        if artifact is None:
            raise NotFoundError("Artifact", str(ref.artifact_id))
        if artifact.ref() != ref:
            message = (
                f"Artifact repository returned a different artifact ref for "
                f"integer artifact {ref.artifact_id}"
            )
            raise ArtifactContractError(message)
        if artifact.inline_payload is None:
            message = (
                f"Integer artifact {ref.artifact_id} does not have an inline "
                f"JSON payload"
            )
            raise ArtifactContractError(message)

        try:
            return IntegerValuePayload.model_validate(artifact.inline_payload).value
        except ValidationError as exc:
            message = (
                f"Failed to resolve artifact {ref.artifact_id} as "
                f"{self.source.id}@{self.source.schema_version} integer value"
            )
            raise ResolutionError(message) from exc


ARITHMETIC.register(
    Artifact(
        spec=INTEGER_VALUE,
        resolver=lambda context: IntegerValueResolver(uow=context.uow),
        writer=lambda context: IntegerValueOutputWriter(uow=context.uow),
    )
)
