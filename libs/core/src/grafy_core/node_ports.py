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


@dataclass(frozen=True, slots=True)
class ServiceContractKey:
    """The id and version of one service contract, without its title or protocol."""

    id: str
    version: int

    def __post_init__(self) -> None:
        if self.id.strip() == "" or self.id != self.id.strip() or " " in self.id:
            raise ValueError(
                "Service contract id must be non-empty without whitespace"
            )
        if len(self.id) > 255:
            raise ValueError("Service contract id must be at most 255 characters")
        if isinstance(self.version, bool) or self.version < 1:
            raise ValueError("Service contract version must be a positive integer")


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
    accepts: ArtifactTypeContract | None
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
    kind: Literal["artifact", "service"] = "artifact"
    service_contracts: tuple[ServiceContractKey, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "service":
            if self.accepts is not None or self.also_accepts:
                raise NodeContractError(
                    f"Input port {self.name!r} is a service port and cannot "
                    "declare an artifact type"
                )
            if not self.service_contracts:
                raise NodeContractError(
                    f"Input port {self.name!r} must name the service contract "
                    "it accepts"
                )
            if self.shape is not PortShape.ONE or self.variadic or self.instance_plugs:
                raise NodeContractError(
                    f"Input port {self.name!r} service port must be one value, "
                    "not variadic or instance plugs"
                )
            return
        if self.service_contracts:
            raise NodeContractError(
                f"Input port {self.name!r} is an artifact port and cannot "
                "declare a service contract"
            )
        if self.accepts is None:
            raise NodeContractError(
                f"Input port {self.name!r} must declare an artifact type"
            )
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

        Empty for a service port and for a port that declares a named artifact
        type variable.
        """

        if self.kind == "service":
            return ()
        accepts = self.accepts
        if not isinstance(accepts, ArtifactTypeKey):
            return ()
        return (accepts, *self.also_accepts)


@dataclass(frozen=True, slots=True)
class OutputPortSpec:
    name: str
    produces: ArtifactTypeContract | None
    title: str | None = None
    description: str | None = None
    shape: PortShape = PortShape.ONE
    required: bool = True
    value_type: type[object] | None = None
    shape_field: str | None = None
    kind: Literal["artifact", "service"] = "artifact"
    service_contracts: tuple[ServiceContractKey, ...] = ()
    # Feature strings a service implementation declares (for example OCR blocks).
    features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "service":
            if self.produces is not None:
                raise NodeContractError(
                    f"Output port {self.name!r} is a service port and cannot "
                    "declare an artifact type"
                )
            if not self.service_contracts:
                raise NodeContractError(
                    f"Output port {self.name!r} must name the service contract "
                    "it produces"
                )
            if self.shape is not PortShape.ONE:
                raise NodeContractError(
                    f"Output port {self.name!r} service port must be one value, "
                    "not variadic or instance plugs"
                )
            return
        if self.service_contracts:
            raise NodeContractError(
                f"Output port {self.name!r} is an artifact port and cannot "
                "declare a service contract"
            )
        if self.produces is None:
            raise NodeContractError(
                f"Output port {self.name!r} must declare an artifact type"
            )


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
