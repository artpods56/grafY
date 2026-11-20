from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grafy_core.runtime.artifact_values import Artifact


MAX_ARTIFACT_CONVERSION_HOPS = 8


@dataclass(frozen=True, slots=True)
class ArtifactConversionKey:
    id: str
    version: int

    def __post_init__(self) -> None:
        if self.id.strip() == "":
            raise ValueError("Artifact conversion id must not be blank")
        if self.version < 1:
            raise ValueError("Artifact conversion version must be positive")


@dataclass(frozen=True, slots=True)
class Conversion[S, T]:
    id: str
    version: int
    title: str
    source: "Artifact[S]"
    target: "Artifact[T]"
    convert: Callable[[S], Awaitable[T]]

    def __post_init__(self) -> None:
        if self.id.strip() == "":
            raise ValueError("Artifact conversion id must not be blank")
        if self.version < 1:
            raise ValueError("Artifact conversion version must be positive")
        if self.title.strip() == "":
            raise ValueError("Artifact conversion title must not be blank")


__all__ = [
    "MAX_ARTIFACT_CONVERSION_HOPS",
    "ArtifactConversionKey",
    "Conversion",
]
