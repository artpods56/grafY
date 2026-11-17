from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey


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


class Ref[T](ArtifactRef):
    """A stored artifact ref. ``T`` is the value class, or ``Any`` when bound."""

    @model_validator(mode="before")
    @classmethod
    def _accept_stored_ref(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        if isinstance(value, ArtifactRef) and not isinstance(
            value, ArtifactRefSequence
        ):
            return value.model_dump()
        return value


class RefSequence[T](ArtifactRefSequence):
    """A stored sequence of artifact refs."""

    @model_validator(mode="before")
    @classmethod
    def _accept_stored_sequence(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        if isinstance(value, ArtifactRefSequence):
            return value.model_dump()
        return value


@dataclass(frozen=True, slots=True)
class Binds:
    """Names the artifact type variable a generic ``Ref`` port takes."""

    variable: str


@dataclass(frozen=True, slots=True)
class Plugs:
    """Plug options that are not part of the value type.

    ``spare`` lets a saved node keep input plugs nothing feeds. A Run ignores
    them. Without it every plug must carry exactly one connection.
    ``agent_default`` is what an Agent tool link does with this input unless
    told otherwise. ``fill`` offers it to the model. ``hidden`` leaves it to
    the Graph.
    """

    variadic: bool = False
    instance: bool = False
    spare: bool = False
    agent_default: Literal["fill", "hidden"] = "fill"

    def __post_init__(self) -> None:
        if self.spare and not self.instance:
            raise NodeContractError("Plugs spare requires instance plugs")


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
    value_types: tuple[type[object], ...] = ()
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
    value_type: type[object] | None = None
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
