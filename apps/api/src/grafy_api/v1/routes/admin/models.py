from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from grafy_core.domain.identity import User


class AdminUserResponse(BaseModel):
    """A user as an operator sees them: who they are and whether they may sign in."""

    id: UUID
    email: str | None
    display_name: str | None
    active: bool
    updated_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "AdminUserResponse":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            active=user.active,
            updated_at=user.updated_at,
        )
