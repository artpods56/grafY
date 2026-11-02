from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
