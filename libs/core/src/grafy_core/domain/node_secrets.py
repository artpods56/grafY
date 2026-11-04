import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import UUID


type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


class InvalidNodeSecretDependenciesError(ValueError):
    pass


def canonical_node_secret_dependencies(
    dependencies: Mapping[str, JsonValue],
) -> bytes:
    try:
        value = json.dumps(
            dict(dependencies),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise InvalidNodeSecretDependenciesError(
            "Node secret dependencies must be canonical JSON values"
        ) from exc
    return value.encode("utf-8")


def node_secret_dependency_sha256(
    dependencies: Mapping[str, JsonValue],
) -> str:
    return sha256(canonical_node_secret_dependencies(dependencies)).hexdigest()


@dataclass(repr=False)
class EncryptedNodeSecret:
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    node_id: str
    name: str
    operator_id: str
    operator_version: int
    key_id: str
    aad_version: int
    dependency_sha256: str
    nonce: bytes
    ciphertext: bytes
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("node_id", self.node_id),
            ("name", self.name),
            ("operator_id", self.operator_id),
            ("key_id", self.key_id),
        ):
            if value.strip() == "":
                raise ValueError(f"Node secret {field_name} must not be empty")
        if len(self.dependency_sha256) != 64:
            raise ValueError("Node secret dependency SHA-256 must be 64 characters")
        if len(self.nonce) != 12:
            raise ValueError("Node secret AES-GCM nonce must be exactly 12 bytes")
        if self.ciphertext == b"":
            raise ValueError("Node secret ciphertext must not be empty")
        if self.operator_version < 1:
            raise ValueError("Node secret operator version must be positive")
        if self.aad_version != 3:
            raise ValueError("Node secret AAD version must be 3")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Node secret timestamps must be timezone-aware")

    def __repr__(self) -> str:
        return (
            "EncryptedNodeSecret("
            f"workspace_id={self.workspace_id!r}, project_id={self.project_id!r}, "
            f"graph_id={self.graph_id!r}, "
            f"node_id={self.node_id!r}, "
            f"name={self.name!r}, operator_id={self.operator_id!r}, "
            f"operator_version={self.operator_version!r}, key_id={self.key_id!r}, "
            f"aad_version={self.aad_version!r}, "
            "nonce=<redacted>, ciphertext=<redacted>)"
        )

    def cache_revision(self) -> str:
        """Return an opaque revision that changes whenever the secret is replaced."""

        digest = sha256(b"grafy-node-secret-state-v3\0")
        digest.update(self.nonce)
        digest.update(self.ciphertext)
        return digest.hexdigest()
