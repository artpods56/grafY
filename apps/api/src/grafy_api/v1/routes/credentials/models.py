from datetime import datetime
from typing import ClassVar
from uuid import UUID

from grafy_core.domain.credentials import (
    PROVIDER_KIND_PATTERN,
    CredentialScope,
    CredentialVerificationStatus,
)
from grafy_core.domain.node_secrets import JsonValue
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter

_VERIFY_CONFIG = TypeAdapter(dict[str, JsonValue])


def verification_config(value: dict[str, object]) -> dict[str, JsonValue]:
    return _VERIFY_CONFIG.validate_python(value)


class CredentialApiModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class CredentialResponse(CredentialApiModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: UUID
    scope: CredentialScope
    provider_kind: str
    label: str
    key_hint: str | None
    usable: bool
    supports_verification: bool
    verification_status: CredentialVerificationStatus
    verification_message: str | None
    verification_hint: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CredentialListResponse(CredentialApiModel):
    credentials: list[CredentialResponse]


class CredentialVerificationResponse(CredentialApiModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    status: CredentialVerificationStatus
    message: str
    account_hint: str | None


class CredentialVerificationFailureDetail(CredentialApiModel):
    verification: CredentialVerificationResponse
    can_save_unverified: bool


class CredentialVerificationFailureResponse(CredentialApiModel):
    detail: CredentialVerificationFailureDetail


class CreateCredentialRequest(CredentialApiModel):
    provider_kind: str = Field(pattern=PROVIDER_KIND_PATTERN)
    label: str = Field(min_length=1, max_length=160)
    value: SecretStr
    verify: bool = True
    save_if_unverified: bool = False
    verify_config: dict[str, object] = Field(default_factory=dict)


class UpdateCredentialRequest(CredentialApiModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    value: SecretStr | None = None
    verify: bool = True
    save_if_unverified: bool = False
    verify_config: dict[str, object] | None = None


class VerifySavedCredentialRequest(CredentialApiModel):
    config: dict[str, object] = Field(default_factory=dict)


class VerifyCandidateCredentialRequest(VerifySavedCredentialRequest):
    provider_kind: str = Field(pattern=PROVIDER_KIND_PATTERN)
    value: SecretStr
