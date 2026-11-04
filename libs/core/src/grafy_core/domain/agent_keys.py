"""One Agent's own model credential, stored sealed (ADR 0021, issue #202).

Whoever configures an Agent may give it an endpoint and key of its own; everyone who can
send to that Agent uses them. The value is write-only: this record holds ciphertext, a
nonce and the id of the key that sealed it, and `__repr__` names the coordinates without
the material, so a log line, a traceback or a debugger cannot print a key.

Sealing is bound to where the Agent sits — Workspace, Project, Graph and Agent id — so a
row copied beside another Agent's coordinates fails to authenticate instead of handing
over someone else's credential. `docs/design/backend-architecture.md` keeps the parallel
with node secrets; the differences are deliberate: an Agent key has no operator contract
to match and needs `edit_project` rather than `manage_secrets`.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID

AGENT_KEY_AAD_VERSION = 1
"""The binding layout this build writes. A record with any other version is unreadable."""


@dataclass(repr=False)
class EncryptedAgentKey:
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    agent_id: str
    key_id: str
    aad_version: int
    nonce: bytes
    ciphertext: bytes
    set_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("graph_id", self.graph_id),
            ("agent_id", self.agent_id),
            ("key_id", self.key_id),
        ):
            if value.strip() == "":
                raise ValueError(f"Agent key {field_name} must not be empty")
        if len(self.nonce) != 12:
            raise ValueError("Agent key AES-GCM nonce must be exactly 12 bytes")
        if self.ciphertext == b"":
            raise ValueError("Agent key ciphertext must not be empty")
        if self.aad_version != AGENT_KEY_AAD_VERSION:
            raise ValueError(
                f"Agent key AAD version must be {AGENT_KEY_AAD_VERSION}"
            )
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Agent key timestamps must be timezone-aware")

    def __repr__(self) -> str:
        return (
            "EncryptedAgentKey("
            f"workspace_id={self.workspace_id!r}, project_id={self.project_id!r}, "
            f"graph_id={self.graph_id!r}, agent_id={self.agent_id!r}, "
            f"key_id={self.key_id!r}, aad_version={self.aad_version!r}, "
            f"set_by_user_id={self.set_by_user_id!r}, "
            "nonce=<redacted>, ciphertext=<redacted>)"
        )

    def cache_revision(self) -> str:
        """An opaque revision that changes whenever the key is replaced."""

        digest = sha256(b"grafy-agent-key-state-v1\0")
        digest.update(self.nonce)
        digest.update(self.ciphertext)
        return digest.hexdigest()


__all__ = ["AGENT_KEY_AAD_VERSION", "EncryptedAgentKey"]
