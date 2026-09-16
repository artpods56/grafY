from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from grafy_core.artifacts import JsonObject


Decision = Literal[
    "dodaj_typ_miejscowosci",
    "brak_podstaw",
    "nie_miejscowosc",
    "niepewne",
]
Confidence = Literal["wysoka", "srednia", "niska"]
TargetKind = Literal["element", "indywidualne"]


class SgkpDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: StrictStr = Field(min_length=1)
    records: list[JsonObject]


class ReferenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: StrictStr = Field(min_length=1)
    name: StrictStr | None = None
    target_kind: TargetKind
    parent_id: StrictStr | None = None
    record_index: StrictInt = Field(ge=0)
    element_index: StrictInt | None = Field(default=None, ge=0)
    text: StrictStr = Field(min_length=1)
    types_before: list[StrictStr]
    settlement_types_before: list[StrictStr]
    candidate_reasons: list[StrictStr]


class SettlementTypeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_name: StrictStr = Field(min_length=1)
    evidence: StrictStr = Field(min_length=1)


class ReferenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: StrictStr = Field(min_length=1)
    name: StrictStr | None = None
    target_kind: TargetKind
    parent_id: StrictStr | None = None
    record_index: StrictInt = Field(ge=0)
    element_index: StrictInt | None = Field(default=None, ge=0)
    decision: Decision
    confidence: Confidence
    settlement_types: list[SettlementTypeEvidence]
    settlement_point_types: list[StrictStr]
    has_administrative_location: StrictBool
    administrative_location_evidence: StrictStr
    reasoning: StrictStr
    types_before: list[StrictStr]
    settlement_types_before: list[StrictStr]
    candidate_reasons: list[StrictStr]
    model: StrictStr = Field(min_length=1)
    prompt_version: StrictStr = Field(min_length=1)
