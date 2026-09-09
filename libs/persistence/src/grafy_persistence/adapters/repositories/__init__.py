"""SQLAlchemy repositories, grouped by the feature they persist."""

from .identity import (
    SqlIdentityRepository as SqlIdentityRepository,
    SqlSecurityAuditRepository as SqlSecurityAuditRepository,
)

from .graphs import (
    SqlSavedGraphRepository as SqlSavedGraphRepository,
    SqlNodeSecretRepository as SqlNodeSecretRepository,
    SqlCollaborationRepository as SqlCollaborationRepository,
)

from .artifacts import (
    SqlArtifactRepository as SqlArtifactRepository,
    SqlStagedUploadRepository as SqlStagedUploadRepository,
)

from .execution import (
    SqlInvocationCacheRepository as SqlInvocationCacheRepository,
    SqlMaterializedNodeOutputsRepository as SqlMaterializedNodeOutputsRepository,
    SqlGraphExecutionHistoryRepository as SqlGraphExecutionHistoryRepository,
)

from .plugins import (
    SqlPluginReleaseRepository as SqlPluginReleaseRepository,
)

from .library import (
    SqlModuleLibraryRepository as SqlModuleLibraryRepository,
    SqlTemplateRepository as SqlTemplateRepository,
)
