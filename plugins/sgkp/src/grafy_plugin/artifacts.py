from typing import cast

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, JsonObject

from grafy_plugin.models import (
    ReferenceCandidate,
    ReferenceDecision,
    SgkpDataset,
)


SGKP_DATASET = ArtifactTypeSpec(
    key=ArtifactTypeKey("sgkp.dataset", 1),
    title="SGKP dataset",
    payload_schema=cast(JsonObject, SgkpDataset.model_json_schema()),
)

SGKP_REFERENCE_CANDIDATE = ArtifactTypeSpec(
    key=ArtifactTypeKey("sgkp.reference.candidate", 1),
    title="SGKP reference candidate",
    payload_schema=cast(JsonObject, ReferenceCandidate.model_json_schema()),
)

SGKP_REFERENCE_DECISION = ArtifactTypeSpec(
    key=ArtifactTypeKey("sgkp.reference.decision", 1),
    title="SGKP reference decision",
    payload_schema=cast(JsonObject, ReferenceDecision.model_json_schema()),
)


__all__ = [
    "SGKP_DATASET",
    "SGKP_REFERENCE_CANDIDATE",
    "SGKP_REFERENCE_DECISION",
    "ReferenceCandidate",
    "ReferenceDecision",
    "SgkpDataset",
]
