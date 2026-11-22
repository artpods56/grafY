import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

PROVIDER_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,127}$"


class CredentialScope(StrEnum):
    PERSONAL = "personal"
    SHARED = "shared"


class CredentialVerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VALID = "valid"
    INVALID = "invalid"
    UNREACHABLE = "unreachable"
    EGRESS_BLOCKED = "egress_blocked"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CredentialVerificationResult:
    status: CredentialVerificationStatus
    message: str
    account_hint: str | None = None

    def __post_init__(self) -> None:
        if not self.message.strip() or len(self.message) > 500:
            raise ValueError("Verification message must contain 1 to 500 characters")
        if self.account_hint is not None and len(self.account_hint) > 255:
            raise ValueError("Verification hint must not exceed 255 characters")


@dataclass(repr=False)
class EncryptedCredential:
    id: UUID
    scope: CredentialScope
    owner_user_id: UUID | None
    workspace_id: UUID | None
    provider_kind: str
    label: str
    key_hint: str | None
    key_id: str
    aad_version: int
    nonce: bytes
    ciphertext: bytes
    verification_status: CredentialVerificationStatus
    verification_message: str | None
    verification_hint: str | None
    verified_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if (self.owner_user_id is not None) != (
            self.scope == CredentialScope.PERSONAL
        ) or (self.workspace_id is not None) != (self.scope == CredentialScope.SHARED):
            raise ValueError("Credential owner must match its scope")
        if re.fullmatch(PROVIDER_KIND_PATTERN, self.provider_kind) is None:
            raise ValueError("Invalid credential provider kind")
        if not self.label.strip() or len(self.label) > 160:
            raise ValueError("Credential label must contain 1 to 160 characters")
        if self.key_hint is not None and len(self.key_hint) > 32:
            raise ValueError("Credential key hint must not exceed 32 characters")
        if self.aad_version != 1 or len(self.nonce) != 12 or not self.ciphertext:
            raise ValueError("Invalid encrypted credential")
        for timestamp in (self.created_at, self.updated_at, self.verified_at):
            if timestamp is not None and timestamp.utcoffset() is None:
                raise ValueError("Credential timestamps must be timezone-aware")

    def __repr__(self) -> str:
        return f"EncryptedCredential(id={self.id!r}, nonce=<redacted>, ciphertext=<redacted>)"

    def cache_revision(self) -> str:
        return sha256(
            b"grafy-credential-v1\0" + self.id.bytes + self.nonce + self.ciphertext
        ).hexdigest()


class SharedCredentialBindingMode(StrEnum):
    CREDENTIAL = "credential"
    PERSONAL = "personal"
    DEPLOYMENT_DEFAULT = "deployment_default"


class UserCredentialOverrideMode(StrEnum):
    CREDENTIAL = "credential"
    SHARED = "shared"
    DEPLOYMENT_DEFAULT = "deployment_default"


@dataclass
class NodeSharedCredentialBinding:
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    node_id: str
    name: str
    mode: SharedCredentialBindingMode
    credential_id: UUID | None
    updated_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class NodeUserCredentialOverride:
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    node_id: str
    name: str
    user_id: UUID
    mode: UserCredentialOverrideMode
    credential_id: UUID | None
    created_at: datetime
    updated_at: datetime
