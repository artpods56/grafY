from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreatedResponse as PersonalAccessTokenCreatedResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenCreateRequest as PersonalAccessTokenCreateRequest,
)
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenResponse as PersonalAccessTokenResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    PersonalAccessTokenScope as PersonalAccessTokenScope,
)
from grafy_api.v1.routes.workspaces.models import (
    UserResponse as UserResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceCreateRequest as WorkspaceCreateRequest,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationCandidateRequest as WorkspaceInvitationCandidateRequest,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationCandidateResponse as WorkspaceInvitationCandidateResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationCreateRequest as WorkspaceInvitationCreateRequest,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationOwnerResponse as WorkspaceInvitationOwnerResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationPersonResponse as WorkspaceInvitationPersonResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationRecipientResponse as WorkspaceInvitationRecipientResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceInvitationWorkspaceResponse as WorkspaceInvitationWorkspaceResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceMemberResponse as WorkspaceMemberResponse,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceMemberRoleRequest as WorkspaceMemberRoleRequest,
)
from grafy_api.v1.routes.workspaces.models import (
    WorkspaceResponse as WorkspaceResponse,
)


class SessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str | None
    display_name: str | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    current: bool
