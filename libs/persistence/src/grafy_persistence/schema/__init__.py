"""Complete SQL schema bootstrap with feature-owned table declarations."""

from grafy_persistence.column_types import (
    ArtifactOutputsType as ArtifactOutputsType,
)
from grafy_persistence.column_types import (
    SavedGraphDocumentType as SavedGraphDocumentType,
)
from grafy_persistence.column_types import (
    UTCDateTime as UTCDateTime,
)

from .artifacts import (
    artifact_objects as artifact_objects,
)
from .artifacts import (
    staged_uploads as staged_uploads,
)
from .base import NAMING_CONVENTION as NAMING_CONVENTION
from .base import metadata as metadata
from .execution import (
    graph_execution_nodes as graph_execution_nodes,
)
from .execution import (
    graph_executions as graph_executions,
)
from .execution import (
    invocation_cache_entries as invocation_cache_entries,
)
from .execution import (
    materialized_node_outputs as materialized_node_outputs,
)
from .graphs import (
    collaborative_graph_heads as collaborative_graph_heads,
)
from .graphs import (
    graph_checkpoint_mappings as graph_checkpoint_mappings,
)
from .graphs import (
    graph_command_receipts as graph_command_receipts,
)
from .graphs import (
    graph_folders as graph_folders,
)
from .graphs import (
    graph_organizations as graph_organizations,
)
from .graphs import (
    node_secrets as node_secrets,
)
from .graphs import (
    saved_graph_revisions as saved_graph_revisions,
)
from .graphs import (
    saved_graphs as saved_graphs,
)
from .graphs import (
    user_graph_states as user_graph_states,
)
from .identity import (
    PlatformTokenScopeTupleType as PlatformTokenScopeTupleType,
)
from .identity import (
    SecurityAuditActorKindType as SecurityAuditActorKindType,
)
from .identity import (
    SecurityAuditOutcomeType as SecurityAuditOutcomeType,
)
from .identity import (
    WorkspaceCapabilityTupleType as WorkspaceCapabilityTupleType,
)
from .identity import (
    WorkspaceInvitationStatusType as WorkspaceInvitationStatusType,
)
from .identity import (
    WorkspaceKindType as WorkspaceKindType,
)
from .identity import (
    WorkspaceRoleType as WorkspaceRoleType,
)
from .identity import (
    auth_sessions as auth_sessions,
)
from .identity import (
    oidc_identities as oidc_identities,
)
from .identity import (
    oidc_login_transactions as oidc_login_transactions,
)
from .identity import (
    personal_access_tokens as personal_access_tokens,
)
from .identity import (
    platform_access_tokens as platform_access_tokens,
)
from .identity import (
    security_audit_events as security_audit_events,
)
from .identity import (
    users as users,
)
from .identity import (
    workspace_invitations as workspace_invitations,
)
from .identity import (
    workspace_memberships as workspace_memberships,
)
from .identity import (
    workspaces as workspaces,
)
from .library import (
    ModulePublicationStateType as ModulePublicationStateType,
)
from .library import (
    TemplateStateType as TemplateStateType,
)
from .library import (
    module_releases as module_releases,
)
from .library import (
    modules as modules,
)
from .library import (
    templates as templates,
)
from .plugins import (
    PluginCapabilityManifestType as PluginCapabilityManifestType,
)
from .plugins import (
    PluginCatalogManifestType as PluginCatalogManifestType,
)
from .plugins import (
    PluginExecutionPolicyType as PluginExecutionPolicyType,
)
from .plugins import (
    PluginFamilyLifecycleType as PluginFamilyLifecycleType,
)
from .plugins import (
    PluginReleaseRevocationReasonType as PluginReleaseRevocationReasonType,
)
from .plugins import (
    PluginReleaseScopeType as PluginReleaseScopeType,
)
from .plugins import (
    PluginRuntimeArtifactType as PluginRuntimeArtifactType,
)
from .plugins import (
    plugin_installations as plugin_installations,
)
from .plugins import (
    plugin_release_revocations as plugin_release_revocations,
)
from .plugins import (
    plugin_release_selections as plugin_release_selections,
)
from .plugins import (
    plugin_releases as plugin_releases,
)

from .execution import transient_executions as transient_executions
