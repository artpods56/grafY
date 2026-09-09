from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from grafy_core.domain.identity import (
    User,
    Workspace,
    WorkspaceCapability,
    WorkspaceInvitationStatus,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
    normalize_workspace_slug,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class WorkspaceResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    kind: WorkspaceKind
    role: WorkspaceRole
    capabilities: tuple[WorkspaceCapability, ...]

    @classmethod
    def from_membership(
        cls, workspace: Workspace, membership: WorkspaceMembership
    ) -> Self:
        return cls(
            id=workspace.id,
            slug=workspace.slug,
            name=workspace.name,
            kind=workspace.kind,
            role=membership.role,
            capabilities=tuple(
                sorted(membership.capabilities, key=lambda item: item.value)
            ),
        )


class UserResponse(BaseModel):
    id: UUID
    email: str | None
    display_name: str | None
    active: bool


class WorkspaceMemberResponse(BaseModel):
    user: UserResponse
    role: WorkspaceRole
    authorization_version: int
    revoked_at: datetime | None

    @classmethod
    def from_membership(cls, user: User, membership: WorkspaceMembership) -> Self:
        return cls(
            user=UserResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                active=user.active,
            ),
            role=membership.role,
            authorization_version=membership.authorization_version,
            revoked_at=membership.revoked_at,
        )


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        return normalize_workspace_slug(value)

    @field_validator("name")
    @classmethod
    def reject_whitespace_only_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must contain a non-whitespace character")
        return value


class WorkspaceInvitationCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip()
        if "@" not in email:
            raise ValueError("email must be a valid address")
        return email


class WorkspaceInvitationCreateRequest(WorkspaceInvitationCandidateRequest):
    role: WorkspaceRole


class WorkspaceInvitationPersonResponse(BaseModel):
    email: str | None
    display_name: str | None


class WorkspaceInvitationCandidateResponse(BaseModel):
    recipient: WorkspaceInvitationPersonResponse


class WorkspaceInvitationOwnerResponse(BaseModel):
    id: UUID
    recipient: WorkspaceInvitationPersonResponse
    role: WorkspaceRole
    status: WorkspaceInvitationStatus
    expires_at: datetime
    created_at: datetime


class WorkspaceInvitationWorkspaceResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class WorkspaceInvitationRecipientResponse(BaseModel):
    id: UUID
    workspace: WorkspaceInvitationWorkspaceResponse
    invited_by: WorkspaceInvitationPersonResponse
    role: WorkspaceRole
    status: WorkspaceInvitationStatus
    expires_at: datetime
    created_at: datetime


class WorkspaceMemberRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: WorkspaceRole


class PersonalAccessTokenScope(StrEnum):
    VIEW_GRAPH = "view_graph"
    VIEW_ARTIFACTS = "view_artifacts"
    VIEW_MATERIALIZATIONS = "view_materializations"
    VIEW_HISTORY = "view_history"
    VIEW_EXECUTION = "view_execution"
    CREATE_GRAPH = "create_graph"
    EDIT_GRAPH = "edit_graph"
    CHECKPOINT_GRAPH = "checkpoint_graph"
    EXECUTE_GRAPH = "execute_graph"
    CANCEL_EXECUTION = "cancel_execution"
    PUBLISH_PLUGIN = "publish_plugin"
    PUBLISH_MODULE = "publish_module"
    MANAGE_SECRETS = "manage_secrets"


class PersonalAccessTokenCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=160)
    scopes: tuple[PersonalAccessTokenScope, ...] = Field(
        min_length=1,
        max_length=len(PersonalAccessTokenScope),
    )
    expires_at: datetime

    @field_validator("label")
    @classmethod
    def reject_whitespace_only_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must contain a non-whitespace character")
        return value

    @field_validator("scopes")
    @classmethod
    def reject_duplicate_scopes(
        cls,
        value: tuple[PersonalAccessTokenScope, ...],
    ) -> tuple[PersonalAccessTokenScope, ...]:
        if len(value) != len(set(value)):
            raise ValueError("PAT scopes must be unique")
        return value


class PersonalAccessTokenResponse(BaseModel):
    id: UUID
    public_prefix: str
    workspace_id: UUID
    label: str
    scopes: tuple[WorkspaceCapability, ...]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None


class PersonalAccessTokenCreatedResponse(PersonalAccessTokenResponse):
    token: SecretStr = Field(
        description="Raw personal access token; returned once and never retrievable again.",
    )
