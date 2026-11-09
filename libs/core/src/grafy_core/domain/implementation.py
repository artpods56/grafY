"""Exact runtime identity of one executable node implementation."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class ImplementationIdentityValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class BuiltinImplementationIdentity(ImplementationIdentityValue):
    kind: Literal["builtin"] = "builtin"
    build_digest: str = Field(pattern=_DIGEST_PATTERN)

    def fingerprint_document(self) -> dict[str, object]:
        return {"kind": self.kind, "build_digest": self.build_digest}

    def provenance_document(self) -> dict[str, object]:
        return self.fingerprint_document()


type ImplementationIdentity = BuiltinImplementationIdentity


__all__ = [
    "BuiltinImplementationIdentity",
    "ImplementationIdentity",
]
