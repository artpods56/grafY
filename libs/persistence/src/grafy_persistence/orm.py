from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import registry

from grafy_core.artifacts import ArtifactObject
from grafy_core.artifacts import JsonObject
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.identity import (
    AuthSession,
    OidcIdentity,
    OidcLoginTransaction,
    PlatformAccessToken,
    PersonalAccessToken,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionScope,
    GraphExecutionStatus,
)
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.module_library import Module, ModuleRelease
from grafy_core.domain.plugin_releases import PluginRelease
from grafy_core.domain.plugin_installations import PluginInstallation
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.collaboration import CollaborativeGraphHead
from grafy_core.domain.saved_graphs import (
    GraphFolder,
    GraphOrganization,
    SavedGraph,
    SavedGraphDocument,
    UserGraphState,
)
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.domain.uploads import Upload
from grafy_core.domain.templates import Template

from grafy_persistence import schema


mapper_registry = registry(metadata=schema.metadata)
metadata = schema.metadata


@dataclass
class SavedGraphRevisionRecord:
    workspace_id: UUID
    graph_id: UUID
    revision: int
    name: str
    document: SavedGraphDocument
    created_at: datetime


@dataclass
class GraphExecutionRecord:
    workspace_id: UUID
    execution_id: UUID
    graph_id: UUID
    graph_revision: int
    status: GraphExecutionStatus
    scope: GraphExecutionScope
    submitted_request: JsonObject | None
    idempotency_key: str | None
    submitted_by_actor_id: UUID | None
    workflow_run_id: UUID | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    def to_domain(self, requested_node_ids: tuple[str, ...]) -> GraphExecution:
        return GraphExecution(
            workspace_id=self.workspace_id,
            execution_id=self.execution_id,
            graph_id=self.graph_id,
            graph_revision=self.graph_revision,
            status=self.status,
            scope=self.scope,
            requested_node_ids=requested_node_ids,
            submitted_request=self.submitted_request,
            idempotency_key=self.idempotency_key,
            submitted_by_actor_id=self.submitted_by_actor_id,
            workflow_run_id=self.workflow_run_id,
            error=self.error,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


def start_mappers() -> None:
    if mapper_registry.mappers:
        return

    mapper_registry.map_imperatively(GraphFolder, schema.graph_folders)
    mapper_registry.map_imperatively(
        SavedGraph,
        schema.saved_graphs,
        version_id_col=schema.saved_graphs.c.revision,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        SavedGraphRevisionRecord,
        schema.saved_graph_revisions,
    )
    mapper_registry.map_imperatively(
        GraphOrganization,
        schema.graph_organizations,
    )
    mapper_registry.map_imperatively(UserGraphState, schema.user_graph_states)
    mapper_registry.map_imperatively(
        ArtifactObject,
        schema.artifact_objects,
    )
    mapper_registry.map_imperatively(
        InvocationCacheEntry,
        schema.invocation_cache_entries,
    )
    mapper_registry.map_imperatively(
        MaterializedNodeOutputs,
        schema.materialized_node_outputs,
    )
    mapper_registry.map_imperatively(
        GraphExecutionRecord,
        schema.graph_executions,
    )
    mapper_registry.map_imperatively(
        EncryptedNodeSecret,
        schema.node_secrets,
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
        PlatformAccessToken,
        schema.platform_access_tokens,
    )
    mapper_registry.map_imperatively(
        SecurityAuditEvent,
        schema.security_audit_events,
    )
    mapper_registry.map_imperatively(Upload, schema.uploads)
    mapper_registry.map_imperatively(
        CollaborativeGraphHead,
        schema.collaborative_graph_heads,
    )
    mapper_registry.map_imperatively(Module, schema.modules)
    mapper_registry.map_imperatively(ModuleRelease, schema.module_releases)
    mapper_registry.map_imperatively(PluginRelease, schema.plugin_releases)
    mapper_registry.map_imperatively(
        PluginInstallation,
        schema.plugin_installations,
    )
    mapper_registry.map_imperatively(
        PluginReleaseRevocation,
        schema.plugin_release_revocations,
    )
    mapper_registry.map_imperatively(
        PluginReleaseSelection,
        schema.plugin_release_selections,
    )
    mapper_registry.map_imperatively(Template, schema.templates)
