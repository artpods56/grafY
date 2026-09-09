from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginReleaseScope,
    PluginRuntimeArtifact,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocationReason
from grafy_core.domain.plugin_selection import PluginFamilyLifecycle
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    text,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import PydanticJSONType, StringEnumType, UTCDateTime

from .base import metadata


class PluginCatalogManifestType(PydanticJSONType[PluginCatalogManifest]):
    model_type = PluginCatalogManifest
    cache_ok = True


class PluginCapabilityManifestType(PydanticJSONType[PluginCapabilityManifest]):
    model_type = PluginCapabilityManifest
    cache_ok = True


class PluginRuntimeArtifactType(PydanticJSONType[PluginRuntimeArtifact]):
    model_type = PluginRuntimeArtifact
    cache_ok = True


class PluginReleaseScopeType(StringEnumType[PluginReleaseScope]):
    impl = String(16)
    enum_type = PluginReleaseScope
    cache_ok = True


class PluginReleaseRevocationReasonType(StringEnumType[PluginReleaseRevocationReason]):
    impl = String(16)
    enum_type = PluginReleaseRevocationReason
    cache_ok = True


class PluginExecutionPolicyType(StringEnumType[PluginExecutionPolicy]):
    impl = String(24)
    enum_type = PluginExecutionPolicy
    cache_ok = True


class PluginFamilyLifecycleType(StringEnumType[PluginFamilyLifecycle]):
    impl = String(16)
    enum_type = PluginFamilyLifecycle
    cache_ok = True


plugin_releases = Table(
    "plugin_releases",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("slug", String(100), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("catalog", PluginCatalogManifestType(), nullable=False),
    Column("contract_digest", String(64), nullable=True),
    Column("capabilities", PluginCapabilityManifestType(), nullable=False),
    Column("capability_digest", String(64), nullable=False),
    Column("protocol_digest", String(64), nullable=True),
    Column("profile_digest", String(64), nullable=True),
    Column("source_object_key", String(2048), nullable=False),
    Column("source_digest", String(64), nullable=False),
    Column("lock_digest", String(64), nullable=False),
    Column("runtime_profile", String(100), nullable=False),
    Column("loader_target", String(255), nullable=False),
    Column("runtime_image_digest", String(64), nullable=True),
    Column("runtime_artifact", PluginRuntimeArtifactType(), nullable=True),
    Column("descriptor_digest", String(64), nullable=True),
    Column(
        "published_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("published_by_platform_actor", String(255), nullable=True),
    Column("published_at", UTCDateTime(), nullable=False),
    CheckConstraint("revision >= 1", name="plugin_release_revision"),
    CheckConstraint(
        "published_by_user_id IS NULL OR published_by_platform_actor IS NULL",
        name="plugin_release_single_publisher",
    ),
    CheckConstraint(
        "length(capability_digest) = 64",
        name="plugin_release_capability_digest",
    ),
    CheckConstraint(
        "length(source_digest) = 64",
        name="plugin_release_source_digest",
    ),
    CheckConstraint(
        "length(lock_digest) = 64",
        name="plugin_release_lock_digest",
    ),
    CheckConstraint(
        "runtime_image_digest IS NULL OR length(runtime_image_digest) = 64",
        name="plugin_release_runtime_image_digest",
    ),
    CheckConstraint(
        "descriptor_digest IS NULL OR length(descriptor_digest) = 64",
        name="plugin_release_descriptor_digest",
    ),
    CheckConstraint(
        "contract_digest IS NULL OR length(contract_digest) = 64",
        name="plugin_release_contract_digest",
    ),
    CheckConstraint(
        "protocol_digest IS NULL OR length(protocol_digest) = 64",
        name="plugin_release_protocol_digest",
    ),
    CheckConstraint(
        "profile_digest IS NULL OR length(profile_digest) = 64",
        name="plugin_release_profile_digest",
    ),
    Index(
        "uq_plugin_releases_slug_revision",
        "slug",
        "revision",
        unique=True,
    ),
    Index(
        "uq_plugin_releases_slug_descriptor",
        "slug",
        "descriptor_digest",
        unique=True,
        sqlite_where=text("descriptor_digest IS NOT NULL"),
        postgresql_where=text("descriptor_digest IS NOT NULL"),
    ),
)


plugin_installations = Table(
    "plugin_installations",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "release_id",
        SaUuid(as_uuid=True),
        ForeignKey("plugin_releases.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("scope", PluginReleaseScopeType(), nullable=False),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("slug", String(100), nullable=False),
    Column("release_revision", Integer, nullable=False),
    Column("execution_policy", PluginExecutionPolicyType(), nullable=False),
    Column(
        "installed_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("installed_by_platform_actor", String(255), nullable=True),
    Column("installed_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "scope IN ('system', 'workspace')",
        name="plugin_installation_scope",
    ),
    CheckConstraint(
        "(scope = 'system' AND workspace_id IS NULL) OR "
        "(scope = 'workspace' AND workspace_id IS NOT NULL)",
        name="plugin_installation_scope_workspace",
    ),
    CheckConstraint(
        "release_revision >= 1",
        name="plugin_installation_release_revision",
    ),
    CheckConstraint(
        "execution_policy IN ('host-eligible', 'isolated-only')",
        name="plugin_installation_execution_policy",
    ),
    CheckConstraint(
        "(scope = 'workspace' AND execution_policy = 'isolated-only') OR "
        "(scope = 'system')",
        name="plugin_installation_scope_policy",
    ),
    CheckConstraint(
        "(scope = 'system' AND installed_by_user_id IS NULL "
        "AND installed_by_platform_actor IS NOT NULL "
        "AND length(trim(installed_by_platform_actor)) BETWEEN 1 AND 255) OR "
        "(scope = 'workspace' AND installed_by_user_id IS NOT NULL "
        "AND installed_by_platform_actor IS NULL)",
        name="plugin_installation_actor",
    ),
    Index(
        "uq_plugin_installations_system_slug_revision",
        "slug",
        "release_revision",
        unique=True,
        sqlite_where=text("scope = 'system'"),
        postgresql_where=text("scope = 'system'"),
    ),
    Index(
        "uq_plugin_installations_workspace_slug_revision",
        "workspace_id",
        "slug",
        "release_revision",
        unique=True,
        sqlite_where=text("scope = 'workspace'"),
        postgresql_where=text("scope = 'workspace'"),
    ),
)


plugin_release_selections = Table(
    "plugin_release_selections",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("scope", PluginReleaseScopeType(), nullable=False),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("slug", String(100), nullable=False),
    Column(
        "selected_release_id",
        SaUuid(as_uuid=True),
        ForeignKey("plugin_releases.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("selected_revision", Integer, nullable=False),
    Column("lifecycle", PluginFamilyLifecycleType(), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    Column("updated_by_actor", String(255), nullable=True),
    CheckConstraint(
        "scope IN ('system', 'workspace')",
        name="plugin_release_selection_scope",
    ),
    CheckConstraint(
        "(scope = 'system' AND workspace_id IS NULL) OR "
        "(scope = 'workspace' AND workspace_id IS NOT NULL)",
        name="plugin_release_selection_scope_workspace",
    ),
    CheckConstraint(
        "selected_revision >= 1",
        name="plugin_release_selection_revision",
    ),
    CheckConstraint(
        "generation >= 1",
        name="plugin_release_selection_generation",
    ),
    CheckConstraint(
        "lifecycle IN ('published', 'deprecated', 'withdrawn')",
        name="plugin_release_selection_lifecycle",
    ),
    CheckConstraint(
        "updated_by_actor IS NULL OR length(trim(updated_by_actor)) BETWEEN 1 AND 255",
        name="plugin_release_selection_actor",
    ),
    Index(
        "uq_plugin_release_selections_system_slug",
        "slug",
        unique=True,
        sqlite_where=text("scope = 'system'"),
        postgresql_where=text("scope = 'system'"),
    ),
    Index(
        "uq_plugin_release_selections_workspace_slug",
        "workspace_id",
        "slug",
        unique=True,
        sqlite_where=text("scope = 'workspace'"),
        postgresql_where=text("scope = 'workspace'"),
    ),
)


plugin_release_revocations = Table(
    "plugin_release_revocations",
    metadata,
    Column(
        "installation_id",
        SaUuid(as_uuid=True),
        ForeignKey("plugin_installations.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("scope", PluginReleaseScopeType(), nullable=False),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("slug", String(100), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("reason", PluginReleaseRevocationReasonType(), nullable=False),
    Column(
        "revoked_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("revoked_by_platform_actor", String(255), nullable=True),
    Column("revoked_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "scope IN ('system', 'workspace')",
        name="revocation_scope",
    ),
    CheckConstraint(
        "(scope = 'system' AND workspace_id IS NULL) OR "
        "(scope = 'workspace' AND workspace_id IS NOT NULL)",
        name="revocation_scope_workspace",
    ),
    CheckConstraint(
        "revision >= 1",
        name="revocation_revision",
    ),
    CheckConstraint(
        "reason IN ('security', 'integrity', 'policy', 'operational')",
        name="revocation_reason",
    ),
    CheckConstraint(
        "(scope = 'system' AND revoked_by_user_id IS NULL "
        "AND revoked_by_platform_actor IS NOT NULL "
        "AND length(trim(revoked_by_platform_actor)) BETWEEN 1 AND 255) OR "
        "(scope = 'workspace' AND revoked_by_user_id IS NOT NULL "
        "AND revoked_by_platform_actor IS NULL)",
        name="revocation_actor",
    ),
    Index(
        "ix_plugin_release_revocations_scoped_identity",
        "scope",
        "workspace_id",
        "slug",
        "revision",
    ),
)
