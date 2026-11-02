from collections.abc import Mapping
from typing import ClassVar, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence


type ArtifactOutputValue = ArtifactRef | ArtifactRefSequence


class ArtifactOutputEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    port: str = Field(min_length=1, max_length=255)
    kind: Literal["single", "sequence"]
    value: ArtifactOutputValue

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        expected_kind = (
            "sequence" if isinstance(self.value, ArtifactRefSequence) else "single"
        )
        if self.kind != expected_kind:
            raise ValueError(
                f"Artifact output {self.port!r} declares kind {self.kind!r}, "
                f"but its value is {expected_kind!r}"
            )
        return self


def normalize_artifact_outputs(
    outputs: dict[str, ArtifactOutputValue],
) -> dict[str, ArtifactOutputValue]:
    normalized: dict[str, ArtifactOutputValue] = {}
    for raw_port, value in outputs.items():
        port = raw_port.strip()
        if port == "":
            raise ValueError("Artifact output port must not be blank")
        if len(port) > 255:
            raise ValueError("Artifact output port must be at most 255 characters")
        if port in normalized:
            raise ValueError(f"Duplicate artifact output port {port!r}")
        normalized[port] = value.model_copy(deep=True)
    return normalized


def artifact_outputs_to_storage(
    outputs: dict[str, ArtifactOutputValue],
) -> list[dict[str, object]]:
    return [
        ArtifactOutputEnvelope(
            port=port,
            kind=("sequence" if isinstance(value, ArtifactRefSequence) else "single"),
            value=value,
        ).model_dump(mode="json")
        for port, value in sorted(outputs.items())
    ]


def artifact_outputs_from_storage(
    value: object,
) -> dict[str, ArtifactOutputValue]:
    if not isinstance(value, list):
        raise ValueError("Artifact outputs storage payload must be a list")
    outputs: dict[str, ArtifactOutputValue] = {}
    for raw_envelope in cast(list[object], value):
        envelope = ArtifactOutputEnvelope.model_validate(raw_envelope)
        if envelope.port in outputs:
            raise ValueError(f"Duplicate artifact output port {envelope.port!r}")
        outputs[envelope.port] = envelope.value
    return outputs


def output_artifact_ids(outputs: Mapping[str, ArtifactOutputValue]) -> set[UUID]:
    """Every artifact identity a recorded output names, sequence items included."""

    artifact_ids: set[UUID] = set()
    for output in outputs.values():
        if isinstance(output, ArtifactRefSequence):
            artifact_ids.update(ref.artifact_id for ref in output.item_refs)
        else:
            artifact_ids.add(output.artifact_id)
    return artifact_ids
