from typing import ClassVar, Literal, Self, cast

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
