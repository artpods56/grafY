import base64
import binascii
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol, cast
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginReleaseScope,
    PluginSecretInputContract,
)
from grafy_core.domain.node_secrets import (
    EncryptedNodeSecret,
    InvalidNodeSecretDependenciesError,
    canonical_node_secret_dependencies,
    node_secret_dependency_sha256,
)
from grafy_core.domain.saved_graphs import (
    SavedGraph,
    SavedGraphNode,
    SavedGraphRevision,
)
from grafy_core.plugins import NodeRegistration, NodeSecretInput, PluginRegistry
from grafy_core.ports.node_secrets import (
    JsonValue,
    NodeSecretResolverPort,
    NodeSecretUnavailableError,
    NodeSecretUnitOfWorkPort,
)


class NodeSecretConfigurationError(RuntimeError):
    pass


class NodeSecretDeclarationError(LookupError):
    pass


class NodeSecretValueError(ValueError):
    pass


class NodeSecretPluginReleaseLookup(Protocol):
    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None: ...


@dataclass(frozen=True, slots=True)
class NodeSecretState:
    node_id: str
    name: str
    configured: bool


@dataclass(frozen=True, slots=True)
class GraphNodeSecretState:
    graph_id: UUID
    graph_revision: int
    secrets: tuple[NodeSecretState, ...]


@dataclass(frozen=True, slots=True)
class _NodeSecretBinding:
    workspace_id: UUID
    graph_id: UUID
    node_id: str
    operator_id: str
    operator_version: int
    name: str
    dependencies: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class _ResolvedNodeSecretContract:
    secret_inputs: tuple[NodeSecretInput | PluginSecretInputContract, ...]
    config: Mapping[str, object]


class NodeSecretService(NodeSecretResolverPort):
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], NodeSecretUnitOfWorkPort],
        plugin_registry: PluginRegistry,
        plugin_release_lookup: NodeSecretPluginReleaseLookup | None = None,
        encryption_key: SecretStr | None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._plugin_registry = plugin_registry
        self._plugin_release_lookup = plugin_release_lookup
        self._encryption_key = encryption_key

    async def status(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphNodeSecretState:
        async with self._unit_of_work_factory() as unit_of_work:
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            stored = await unit_of_work.node_secrets.list_for_graph(
                workspace_id,
                graph_id,
            )
        stored_by_key = {(secret.node_id, secret.name): secret for secret in stored}
        active_key_id = self._active_key_id()

        states: list[NodeSecretState] = []
        for node in graph.document.nodes:
            contract = await self._resolved_node_secret_contract(
                graph.workspace_id,
                node,
            )
            if contract is None:
                continue
            for declaration in contract.secret_inputs:
                dependencies = self._declared_dependencies(
                    declaration,
                    contract.config,
                )
                record = stored_by_key.get((node.id, declaration.name))
                configured = (
                    record is not None
                    and record.operator_id == node.operator_id
                    and record.operator_version == node.operator_version
                    and active_key_id is not None
                    and record.key_id == active_key_id
                    and record.dependency_sha256
                    == node_secret_dependency_sha256(dependencies)
                )
                states.append(
                    NodeSecretState(
                        node_id=node.id,
                        name=declaration.name,
                        configured=configured,
                    )
                )
        return GraphNodeSecretState(
            graph_id=graph.id,
            graph_revision=graph.revision,
            secrets=tuple(states),
        )

    async def configure(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        node_id: str,
        name: str,
        value: SecretStr,
        expected_graph_revision: int,
    ) -> NodeSecretState:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.graphs.lock_revision(
                workspace_id,
                graph_id,
                expected_graph_revision,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            graph.ensure_revision(expected_graph_revision)
            binding = await self._binding(graph, node_id, name)

            plaintext = value.get_secret_value()
            if plaintext == "":
                raise NodeSecretValueError("Node secret value must not be empty")
            plaintext_bytes = plaintext.encode("utf-8")
            if len(plaintext_bytes) > 65_536:
                raise NodeSecretValueError(
                    "Node secret value must not exceed 65536 UTF-8 bytes"
                )
            key, key_id = self._resolved_encryption_key()
            nonce = os.urandom(12)
            aad_version = 2
            aad = self._additional_authenticated_data(binding, aad_version)
            ciphertext = AESGCM(key).encrypt(nonce, plaintext_bytes, aad)
            now = datetime.now(UTC)
            encrypted = EncryptedNodeSecret(
                workspace_id=binding.workspace_id,
                graph_id=binding.graph_id,
                node_id=binding.node_id,
                name=binding.name,
                operator_id=binding.operator_id,
                operator_version=binding.operator_version,
                key_id=key_id,
                aad_version=aad_version,
                dependency_sha256=node_secret_dependency_sha256(binding.dependencies),
                nonce=nonce,
                ciphertext=ciphertext,
                created_at=now,
                updated_at=now,
            )
            await unit_of_work.node_secrets.upsert(encrypted)
            await unit_of_work.commit()
        return NodeSecretState(node_id=node_id, name=name, configured=True)

    async def remove(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        node_id: str,
        name: str,
        expected_graph_revision: int,
    ) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.graphs.lock_revision(
                workspace_id,
                graph_id,
                expected_graph_revision,
            )
            graph = await unit_of_work.graphs.get(workspace_id, graph_id)
            if graph is None:
                raise NotFoundError("Saved graph", str(graph_id))
            graph.ensure_revision(expected_graph_revision)
            await self._binding(graph, node_id, name)
            await unit_of_work.node_secrets.remove(
                workspace_id,
                graph_id,
                node_id,
                name,
            )
            await unit_of_work.commit()

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> SecretStr:
        binding, encrypted = await self._validated_secret_record(
            graph_id=graph_id,
            workspace_id=workspace_id,
            graph_revision=graph_revision,
            node_id=node_id,
            name=name,
            dependencies=dependencies,
        )

        key, key_id = self._resolved_encryption_key()
        if encrypted.key_id != key_id:
            raise NodeSecretUnavailableError(
                "Configured node secret cannot be decrypted by this server"
            )
        try:
            aad = self._additional_authenticated_data(binding, encrypted.aad_version)
            plaintext = AESGCM(key).decrypt(
                encrypted.nonce,
                encrypted.ciphertext,
                aad,
            )
        except (InvalidTag, ValueError) as exc:
            raise NodeSecretUnavailableError(
                "Configured node secret cannot be decrypted by this server"
            ) from exc
        try:
            decoded = plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NodeSecretUnavailableError(
                "Configured node secret contains invalid encoded data"
            ) from exc
        return SecretStr(decoded)

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        _, encrypted = await self._validated_secret_record(
            graph_id=graph_id,
            workspace_id=workspace_id,
            graph_revision=graph_revision,
            node_id=node_id,
            name=name,
            dependencies=dependencies,
        )
        _, active_key_id = self._resolved_encryption_key()
        if encrypted.key_id != active_key_id:
            raise NodeSecretUnavailableError(
                "Configured node secret cannot be decrypted by this server"
            )
        return encrypted.cache_revision()

    async def _validated_secret_record(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID | None,
        graph_revision: int | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> tuple[_NodeSecretBinding, EncryptedNodeSecret]:
        if graph_id is None or graph_revision is None or node_id is None:
            raise NodeSecretUnavailableError(
                "A saved graph context is required to resolve a node secret"
            )
        async with self._unit_of_work_factory() as unit_of_work:
            graph_revision_snapshot = await unit_of_work.graphs.get_revision(
                workspace_id,
                graph_id,
                graph_revision,
            )
            if graph_revision_snapshot is None:
                raise NotFoundError(
                    "Saved graph revision",
                    f"{graph_id}@{graph_revision}",
                )
            binding = await self._binding(graph_revision_snapshot, node_id, name)
            submitted_dependencies = dict(dependencies)
            try:
                dependencies_match = canonical_node_secret_dependencies(
                    submitted_dependencies
                ) == canonical_node_secret_dependencies(binding.dependencies)
            except InvalidNodeSecretDependenciesError as exc:
                raise NodeSecretUnavailableError(
                    "Node secret dependencies must be canonical JSON values"
                ) from exc
            if not dependencies_match:
                raise NodeSecretUnavailableError(
                    "Configured node secret does not match the saved node configuration"
                )
            encrypted = await unit_of_work.node_secrets.get(
                workspace_id,
                graph_id,
                node_id,
                name,
            )
        if encrypted is None:
            raise NodeSecretUnavailableError("Required node secret is not configured")
        expected_dependency_sha256 = node_secret_dependency_sha256(binding.dependencies)
        if (
            encrypted.operator_id != binding.operator_id
            or encrypted.operator_version != binding.operator_version
            or encrypted.dependency_sha256 != expected_dependency_sha256
        ):
            raise NodeSecretUnavailableError(
                "Configured node secret does not match the saved node configuration"
            )
        return binding, encrypted

    async def _binding(
        self,
        graph: SavedGraph | SavedGraphRevision,
        node_id: str,
        name: str,
    ) -> _NodeSecretBinding:
        node = next(
            (
                candidate
                for candidate in graph.document.nodes
                if candidate.id == node_id
            ),
            None,
        )
        if node is None:
            raise NodeSecretDeclarationError(
                f"Node {node_id!r} does not exist in graph {graph.id}"
            )
        contract = await self._resolved_node_secret_contract(
            graph.workspace_id,
            node,
        )
        if contract is None:
            pin = node.plugin_release_pin
            if pin is not None and self._plugin_release_lookup is not None:
                raise NodeSecretDeclarationError(
                    f"Node {node_id!r} uses an unavailable operator in pinned "
                    f"{pin.scope.value} Plugin release {pin.slug!r} revision "
                    f"{pin.revision}"
                )
            raise NodeSecretDeclarationError(
                f"Node {node_id!r} uses an unavailable operator"
            )
        declaration = next(
            (
                candidate
                for candidate in contract.secret_inputs
                if candidate.name == name
            ),
            None,
        )
        if declaration is None:
            raise NodeSecretDeclarationError(
                f"Node {node_id!r} does not declare secret input {name!r}"
            )
        return _NodeSecretBinding(
            workspace_id=graph.workspace_id,
            graph_id=graph.id,
            node_id=node.id,
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            name=declaration.name,
            dependencies=self._declared_dependencies(
                declaration,
                contract.config,
            ),
        )

    async def _resolved_node_secret_contract(
        self,
        workspace_id: UUID,
        node: SavedGraphNode,
    ) -> _ResolvedNodeSecretContract | None:
        pin = node.plugin_release_pin
        if pin is not None and self._plugin_release_lookup is not None:
            release = await self._plugin_release_lookup.get_by_revision(
                workspace_id,
                pin.slug,
                pin.revision,
                scope=pin.scope,
            )
            if release is None:
                return None
            node_contract = next(
                (
                    candidate
                    for candidate in release.release.catalog.nodes
                    if candidate.operator_id == node.operator_id
                    and candidate.operator_version == node.operator_version
                ),
                None,
            )
            if node_contract is None:
                return None
            return _ResolvedNodeSecretContract(
                secret_inputs=node_contract.secret_inputs,
                config=node.config_dict(),
            )

        registration = self._registration(node.operator_id, node.operator_version)
        if registration is None:
            return None
        config = registration.node_class.config_contract.model.model_validate(
            node.config_dict()
        ).model_dump(mode="json")
        return _ResolvedNodeSecretContract(
            secret_inputs=registration.secret_inputs,
            config=config,
        )

    def _registration(
        self,
        operator_id: str,
        operator_version: int,
    ) -> NodeRegistration | None:
        return next(
            (
                registration
                for registration in self._plugin_registry.nodes
                if registration.key == (operator_id, operator_version)
            ),
            None,
        )

    @staticmethod
    def _declared_dependencies(
        declaration: NodeSecretInput | PluginSecretInputContract,
        config: Mapping[str, object],
    ) -> dict[str, JsonValue]:
        return {
            dependency: cast(JsonValue, config[dependency])
            for dependency in declaration.config_dependencies
        }

    @classmethod
    def _additional_authenticated_data(
        cls,
        binding: _NodeSecretBinding,
        aad_version: int,
    ) -> bytes:
        identity = {
            "version": aad_version,
            "graph_id": str(binding.graph_id),
            "node_id": binding.node_id,
            "operator_id": binding.operator_id,
            "operator_version": binding.operator_version,
            "name": binding.name,
            "dependencies": binding.dependencies,
        }
        if aad_version == 2:
            identity["workspace_id"] = str(binding.workspace_id)
        elif aad_version != 1:
            raise ValueError("Unsupported node secret AAD version")
        return json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _resolved_encryption_key(self) -> tuple[bytes, str]:
        if self._encryption_key is None:
            raise NodeSecretConfigurationError(
                "GRAFY_CREDENTIAL_ENCRYPTION_KEY is required for node secret operations"
            )
        encoded = self._encryption_key.get_secret_value()
        try:
            key = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise NodeSecretConfigurationError(
                "GRAFY_CREDENTIAL_ENCRYPTION_KEY must be valid base64"
            ) from exc
        if len(key) != 32:
            raise NodeSecretConfigurationError(
                "GRAFY_CREDENTIAL_ENCRYPTION_KEY must decode to exactly 32 bytes"
            )
        return key, sha256(key).hexdigest()[:16]

    def _active_key_id(self) -> str | None:
        try:
            _, key_id = self._resolved_encryption_key()
        except NodeSecretConfigurationError:
            return None
        return key_id
