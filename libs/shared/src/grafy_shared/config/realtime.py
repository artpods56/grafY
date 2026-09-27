"""Graph-room presence and heartbeat timing."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class RealtimeConfig(BaseSettings):
    """Presence expiry and the WebSocket room heartbeat cadence."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    # Application graph-room heartbeat interval. Zero disables heartbeats
    # (useful for focused unit tests). Production default revalidates membership
    # when post-commit room invalidation is lost.
    graph_room_heartbeat_seconds: float = Field(default=15.0, ge=0.0, le=120.0)
    # Ephemeral presence: clear cursor/activity after TTL; remove idle entries at 2×.
    graph_room_presence_ttl_seconds: float = Field(default=5.0, ge=0.5, le=120.0)
    # Best-effort cursor budget (~20 Hz). Excess updates are dropped, not rejected.
    graph_room_presence_max_updates_per_second: float = Field(
        default=20.0,
        ge=1.0,
        le=60.0,
    )
