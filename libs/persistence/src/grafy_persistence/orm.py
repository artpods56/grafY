from sqlalchemy.orm import registry

from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.agent_keys import EncryptedAgentKey
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.identity import (
    AuthSession,
    OidcIdentity,
    OidcLoginTransaction,
    PersonalAccessToken,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.projects import (
    Project,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.domain.uploads import Upload

from grafy_persistence import schema


mapper_registry = registry(metadata=schema.metadata)
metadata = schema.metadata


def start_mappers() -> None:
    if mapper_registry.mappers:
        return

    # Project aggregate and its collaboration head. The repositories themselves speak
    # Core SQL, but the mappers stay registered so identity, artifact and secret
    # persistence share one registry and one metadata.
    mapper_registry.map_imperatively(Project, schema.projects)
    mapper_registry.map_imperatively(ProjectFolder, schema.project_folders)
    mapper_registry.map_imperatively(ProjectOrganization, schema.project_organizations)
    mapper_registry.map_imperatively(UserProjectState, schema.user_project_states)
    mapper_registry.map_imperatively(ProjectHead, schema.project_heads)

    mapper_registry.map_imperatively(
        ArtifactObject,
        schema.artifact_objects,
    )
    mapper_registry.map_imperatively(
        EncryptedNodeSecret,
        schema.node_secrets,
    )
    mapper_registry.map_imperatively(
        EncryptedAgentKey,
        schema.agent_keys,
    )
    mapper_registry.map_imperatively(User, schema.users)
    mapper_registry.map_imperatively(OidcIdentity, schema.oidc_identities)
    mapper_registry.map_imperatively(
        OidcLoginTransaction,
        schema.oidc_login_transactions,
    )
    mapper_registry.map_imperatively(Workspace, schema.workspaces)
    mapper_registry.map_imperatively(
        WorkspaceMembership,
        schema.workspace_memberships,
    )
    mapper_registry.map_imperatively(
        WorkspaceInvitation,
        schema.workspace_invitations,
    )
    mapper_registry.map_imperatively(AuthSession, schema.auth_sessions)
    mapper_registry.map_imperatively(
        PersonalAccessToken,
        schema.personal_access_tokens,
    )
    mapper_registry.map_imperatively(
        SecurityAuditEvent,
        schema.security_audit_events,
    )
    mapper_registry.map_imperatively(Upload, schema.uploads)
