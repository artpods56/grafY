from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec


class PortShape(StrEnum):
    ONE = "one"
    MANY = "many"


class NodeContractError(TypeError):
    pass


class NodeContractResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactTypeVariable:
    """A named artifact type chosen when a node instance is bound."""

    name: str

    def __post_init__(self) -> None:
        if self.name.strip() == "":
            raise ValueError("Artifact type variable name must not be empty")
        if self.name != self.name.strip():
            raise ValueError(
                "Artifact type variable name must not have surrounding whitespace"
            )
        if len(self.name) > 255:
            raise ValueError(
                "Artifact type variable name must be at most 255 characters"
            )


ArtifactTypeContract = ArtifactTypeKey | ArtifactTypeVariable


@dataclass(frozen=True, slots=True)
class InPort:
    """Marks an input model field as an artifact port via Annotated metadata.

    ``accepts`` is the primary artifact type (or the single artifact type
    variable). ``also_accepts`` adds the remaining concrete types the same input
    accepts, so one port can take several artifact types without a type variable.
    ``shape_field`` names the node config field that chooses this port's shape
    for one node instance; the field holds ``one`` or ``many``.
    ``spare_plugs`` lets a saved node keep input plugs nothing feeds, the spare an
    editor holds ready for the port's next member; a Run ignores them. Without it
    every plug must carry exactly one connection.
    """

    accepts: ArtifactTypeSpec | ArtifactTypeContract
    variadic: bool = False
    instance_plugs: bool = False
    spare_plugs: bool = False
    also_accepts: tuple[ArtifactTypeSpec | ArtifactTypeKey, ...] = ()
    shape_field: str | None = None
    agent_default: Literal["fill", "hidden"] = "fill"
    """What an Agent tool link does with this input unless told otherwise.

    ``fill`` offers it to the model as a parameter; ``hidden`` leaves it to the Graph. An
    input that makes the node fetch whatever address a model writes is hidden by default."""

    def __post_init__(self) -> None:
        if self.also_accepts and isinstance(self.accepts, ArtifactTypeVariable):
            raise NodeContractError(
                "An input port must declare either an artifact type variable or "
                "additional accepted artifact types, not both"
            )
        if self.shape_field is not None and (self.variadic or self.instance_plugs):
            raise NodeContractError(
                "A config-chosen port shape cannot be variadic or use instance plugs"
            )
        if self.spare_plugs and not self.instance_plugs:
            raise NodeContractError("Spare plugs require instance plugs")


@dataclass(frozen=True, slots=True)
class OutPort:
    """Marks an output model field as an artifact port via Annotated metadata.

    ``shape_field`` names the node config field that chooses this port's shape
    for one node instance; the field holds ``one`` or ``many``.
    """

    produces: ArtifactTypeSpec | ArtifactTypeContract
    shape_field: str | None = None


@dataclass(frozen=True, slots=True)
class InputPortSpec:
    name: str
    accepts: ArtifactTypeContract
    title: str | None = None
    description: str | None = None
    shape: PortShape = PortShape.ONE
    variadic: bool = False
    instance_plugs: bool = False
    spare_plugs: bool = False
    accepted_shapes: tuple[PortShape, ...] = (PortShape.ONE,)
    target_type: type[object] | None = None
    preserves_ref_container: bool = False
    allows_none: bool = False
    required: bool = True
    also_accepts: tuple[ArtifactTypeKey, ...] = ()
    shape_field: str | None = None
    agent_default: Literal["fill", "hidden"] = "fill"

    def __post_init__(self) -> None:
        if not self.also_accepts:
            return
        if isinstance(self.accepts, ArtifactTypeVariable):
            raise NodeContractError(
                f"Input port {self.name!r} must declare either an artifact type "
                "variable or additional accepted artifact types, not both"
            )
        if self.accepts in self.also_accepts:
            raise NodeContractError(
                f"Input port {self.name!r} repeats its primary artifact type "
                "among its additional accepted artifact types"
            )
        if len(set(self.also_accepts)) != len(self.also_accepts):
            raise NodeContractError(
                f"Input port {self.name!r} declares duplicate additional accepted "
                "artifact types"
            )

    @property
    def accepted_types(self) -> tuple[ArtifactTypeKey, ...]:
        """Concrete artifact types this input accepts, primary type first.

        Empty for a port that declares a named artifact type variable.
        """

        if isinstance(self.accepts, ArtifactTypeVariable):
            return ()
        return (self.accepts, *self.also_accepts)


@dataclass(frozen=True, slots=True)
class OutputPortSpec:
    name: str
    produces: ArtifactTypeContract
    title: str | None = None
    description: str | None = None
    shape: PortShape = PortShape.ONE
    required: bool = True
    shape_field: str | None = None


@dataclass(frozen=True, slots=True)
class InputContract[T: BaseModel]:
    model: type[T]
    ports: dict[str, InputPortSpec]


@dataclass(frozen=True, slots=True)
class OutputContract[T: BaseModel]:
    model: type[T]
    ports: dict[str, OutputPortSpec]


@dataclass(frozen=True, slots=True)
class ConfigContract[T: BaseModel]:
    model: type[T]


@dataclass(frozen=True, slots=True)
class ResolvedNodeContracts:
    input_contract: InputContract[Any]
    output_contract: OutputContract[Any]
