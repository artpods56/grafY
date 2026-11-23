import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Literal, TypeGuard, cast
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import AnyHttpUrl, SecretStr, TypeAdapter, ValidationError

from grafy_shared.config import ProviderSecretsConfig

from grafy_api.credentials import CredentialService, CredentialValueError
from grafy_core.domain.credentials import (
    CredentialScope,
    CredentialVerificationResult,
    CredentialVerificationStatus,
    EncryptedCredential,
    NodeSharedCredentialBinding,
    NodeUserCredentialOverride,
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.node_secrets import (
    EncryptedNodeSecret,
    InvalidNodeSecretDependenciesError,
    canonical_node_secret_dependencies,
    node_secret_dependency_sha256,
)
from grafy_core.domain.graph_documents import GraphNode
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import CollaborationHeadConflictError
from grafy_core.kernel.project import GraphDefinition, ProjectDocumentError
from grafy_core.plugins import NodeRegistration, NodeSecretInput, PluginRegistry
from grafy_core.ports.node_secrets import (
    JsonValue,
    NodeSecretResolverPort,
    NodeSecretUnavailableError,
    NodeSecretUnitOfWorkPort,
)
from grafy_api.credential_keys import (
    CredentialKeyConfigurationError,
    resolve_credential_encryption_key,
)

logger = logging.getLogger(__name__)


class NodeSecretConfigurationError(RuntimeError):
    pass


class NodeSecretDeclarationError(LookupError):
    pass


class NodeSecretValueError(ValueError):
    pass


class NodeSecretResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"


class NodeSecretResolutionReason(StrEnum):
    CONTRACT_UNAVAILABLE = "contract_unavailable"
    INVALID_CONFIGURATION = "invalid_configuration"


type NodeSecretSource = Literal[
    "personal_credential",
    "shared_credential",
    "deployment_default",
    "inline_legacy",
    "none",
]


@dataclass(frozen=True, slots=True)
class NodeSecretState:
    node_id: str
    name: str
    configured: bool
    provider_kind: str = "generic"
    effective_source: NodeSecretSource = "none"
    effective_credential_id: UUID | None = None
    effective_credential_label: str | None = None
    effective_verification_status: CredentialVerificationStatus | None = None
    shared_binding_mode: SharedCredentialBindingMode | Literal["none"] = "none"
    shared_credential_id: UUID | None = None
    shared_credential_label: str | None = None
    shared_credential_missing: bool = False
    personal_override_mode: UserCredentialOverrideMode | Literal["none"] = "none"
    personal_credential_id: UUID | None = None
    personal_credential_label: str | None = None
    deployment_default_available: bool = False
    supports_verification: bool = False


@dataclass(frozen=True, slots=True)
class NodeSecretResolutionState:
    node_id: str
    status: NodeSecretResolutionStatus
    reason: NodeSecretResolutionReason


@dataclass(frozen=True, slots=True)
class GraphNodeSecretState:
    project_id: UUID
    graph_id: str
    head_sequence: int
    secrets: tuple[NodeSecretState, ...]
    unresolved_nodes: tuple[NodeSecretResolutionState, ...]


@dataclass(frozen=True, slots=True)
class _NodeSecretBinding:
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    node_id: str
    operator_id: str
    operator_version: int
    declaration: NodeSecretInput
    dependencies: dict[str, JsonValue]

    @property
    def name(self) -> str:
        return self.declaration.name

    @property
    def key(self) -> tuple[UUID, UUID, str, str, str]:
        return (
            self.workspace_id,
            self.project_id,
            self.graph_id,
            self.node_id,
            self.name,
        )


@dataclass(frozen=True, slots=True)
class _ResolvedNodeSecretContract:
    secret_inputs: tuple[NodeSecretInput, ...]
    config: Mapping[str, object]


class NodeSecretService(NodeSecretResolverPort):
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], NodeSecretUnitOfWorkPort],
        plugin_registry: PluginRegistry,
        encryption_key: SecretStr | None,
        provider_secrets: ProviderSecretsConfig | None = None,
        credentials: CredentialService | None = None,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._plugin_registry = plugin_registry
        self._encryption_key = encryption_key
        self._provider_secrets = provider_secrets or ProviderSecretsConfig()
        self._credentials = credentials

    async def status(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        *,
        actor_user_id: UUID | None = None,
    ) -> GraphNodeSecretState:
        async with self._uow_factory() as uow:
            head = await self._head(uow, workspace_id, project_id)
            graph = self._graph(head, graph_id)
            stored = await uow.node_secrets.list_for_graph(
                workspace_id,
                project_id,
                graph_id,
            )
            shared = {}
            overrides = {}
            records: dict[UUID, EncryptedCredential] = {}
            if self._credentials is not None:
                repo = uow.node_credential_selections
                shared = {
                    (row.node_id, row.name): row
                    for row in await repo.list_shared_bindings_for_graph(
                        workspace_id, project_id, graph_id
                    )
                }
                records.update(
                    (row.id, row)
                    for row in await uow.credentials.list_shared(workspace_id)
                )
                if actor_user_id is not None:
                    overrides = {
                        (row.node_id, row.name): row
                        for row in await repo.list_user_overrides_for_graph(
                            workspace_id, project_id, graph_id, actor_user_id
                        )
                    }
                    records.update(
                        (row.id, row)
                        for row in await uow.credentials.list_personal(actor_user_id)
                    )
        stored_by_key = {(secret.node_id, secret.name): secret for secret in stored}

        states: list[NodeSecretState] = []
        unresolved_nodes: list[NodeSecretResolutionState] = []
        for node in graph.document.nodes:
            try:
                contract = await self._resolved_node_secret_contract(node)
            except ValidationError:
                reason = NodeSecretResolutionReason.INVALID_CONFIGURATION
                logger.warning(
                    "node_secret_status_unresolved",
                    extra={"node_id": node.id, "reason": reason.value},
                )
                unresolved_nodes.append(
                    NodeSecretResolutionState(
                        node_id=node.id,
                        status=NodeSecretResolutionStatus.UNRESOLVED,
                        reason=reason,
                    )
                )
                continue
            if contract is None:
                reason = NodeSecretResolutionReason.CONTRACT_UNAVAILABLE
                logger.warning(
                    "node_secret_status_unresolved",
                    extra={"node_id": node.id, "reason": reason.value},
                )
                unresolved_nodes.append(
                    NodeSecretResolutionState(
                        node_id=node.id,
                        status=NodeSecretResolutionStatus.UNRESOLVED,
                        reason=reason,
                    )
                )
                continue
            for declaration in contract.secret_inputs:
                binding = _NodeSecretBinding(
                    workspace_id,
                    project_id,
                    graph_id,
                    node.id,
                    node.operator_id,
                    node.operator_version,
                    declaration,
                    self._declared_dependencies(declaration, contract.config),
                )
                key = node.id, declaration.name
                states.append(
                    self._state(
                        binding,
                        stored_by_key.get(key),
                        shared.get(key),
                        overrides.get(key),
                        records,
                        actor_user_id,
                    )
                )
        return GraphNodeSecretState(
            project_id=project_id,
            graph_id=graph_id,
            head_sequence=head.collaboration_sequence,
            secrets=tuple(states),
            unresolved_nodes=tuple(unresolved_nodes),
        )

    async def configure(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        value: SecretStr,
        expected_head_sequence: int,
    ) -> NodeSecretState:
        async with self._uow_factory() as uow:
            head = await self._head(uow, workspace_id, project_id, lock=True)
            if head.collaboration_sequence != expected_head_sequence:
                raise CollaborationHeadConflictError(
                    workspace_id=workspace_id,
                    graph_id=project_id,
                    expected_sequence=expected_head_sequence,
                    actual_sequence=head.collaboration_sequence,
                    room_epoch=head.room_epoch,
                )
            binding = await self._binding(head, graph_id, node_id, name)

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
            aad_version = 3
            aad = self._additional_authenticated_data(binding, aad_version)
            ciphertext = AESGCM(key).encrypt(nonce, plaintext_bytes, aad)
            now = datetime.now(UTC)
            encrypted = EncryptedNodeSecret(
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
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
            await uow.node_secrets.upsert(encrypted)
            await uow.commit()
        return NodeSecretState(
            node_id=node_id,
            name=name,
            configured=True,
            effective_source="inline_legacy",
        )

    async def remove(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        expected_head_sequence: int,
    ) -> None:
        async with self._uow_factory() as uow:
            head = await self._head(uow, workspace_id, project_id, lock=True)
            if head.collaboration_sequence != expected_head_sequence:
                raise CollaborationHeadConflictError(
                    workspace_id=workspace_id,
                    graph_id=project_id,
                    expected_sequence=expected_head_sequence,
                    actual_sequence=head.collaboration_sequence,
                    room_epoch=head.room_epoch,
                )
            await self._binding(head, graph_id, node_id, name)
            await uow.node_secrets.remove(
                workspace_id,
                project_id,
                graph_id,
                node_id,
                name,
            )
            await uow.commit()

    async def set_shared_binding(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        mode: SharedCredentialBindingMode | Literal["none"],
        credential_id: UUID | None,
        actor_user_id: UUID,
        expected_head_sequence: int,
    ) -> NodeSecretState:
        async with self._uow_factory() as uow:
            head = await self._head(uow, workspace_id, project_id, lock=True)
            if head.collaboration_sequence != expected_head_sequence:
                raise CollaborationHeadConflictError(
                    workspace_id=workspace_id,
                    graph_id=project_id,
                    expected_sequence=expected_head_sequence,
                    actual_sequence=head.collaboration_sequence,
                    room_epoch=head.room_epoch,
                )
            binding = await self._binding(head, graph_id, node_id, name)
            await self._validate_selection(uow, binding, mode, credential_id, None)
            if mode == "none":
                await uow.node_credential_selections.delete_shared_binding(*binding.key)
            else:
                now = datetime.now(UTC)
                await uow.node_credential_selections.upsert_shared_binding(
                    NodeSharedCredentialBinding(
                        *binding.key, mode, credential_id, actor_user_id, now, now
                    )
                )
            await uow.commit()
        return await self._selection_status(binding, actor_user_id)

    async def set_personal_override(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        mode: UserCredentialOverrideMode | Literal["none"],
        credential_id: UUID | None,
        actor_user_id: UUID,
    ) -> NodeSecretState:
        async with self._uow_factory() as uow:
            head = await self._head(uow, workspace_id, project_id, lock=True)
            binding = await self._binding(head, graph_id, node_id, name)
            await self._validate_selection(
                uow, binding, mode, credential_id, actor_user_id
            )
            if mode == "none":
                await uow.node_credential_selections.delete_user_override(
                    *binding.key, actor_user_id
                )
            else:
                now = datetime.now(UTC)
                await uow.node_credential_selections.upsert_user_override(
                    NodeUserCredentialOverride(
                        *binding.key, actor_user_id, mode, credential_id, now, now
                    )
                )
            await uow.commit()
        return await self._selection_status(binding, actor_user_id)

    async def _selection_status(
        self, binding: _NodeSecretBinding, actor_user_id: UUID
    ) -> NodeSecretState:
        async with self._uow_factory() as uow:
            shared, override, records = await self._load_selection(
                uow, binding, actor_user_id
            )
            inline = await uow.node_secrets.get(*binding.key)
            return self._state(
                binding, inline, shared, override, records, actor_user_id
            )

    async def verify(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        actor_user_id: UUID,
        value: SecretStr | None,
    ) -> CredentialVerificationResult:
        credentials = self._credential_service()
        credentials.check_verify_rate(actor_user_id)
        async with self._uow_factory() as uow:
            head = await self._head(uow, workspace_id, project_id)
            binding = await self._binding(head, graph_id, node_id, name)
            if value is None:
                value = await self._resolve_binding(uow, binding, actor_user_id)
        return await credentials.verify_candidate(
            provider_kind=binding.declaration.provider_kind,
            value=value,
            config=binding.dependencies,
        )

    async def _validate_selection(
        self,
        uow: NodeSecretUnitOfWorkPort,
        binding: _NodeSecretBinding,
        mode: SharedCredentialBindingMode
        | UserCredentialOverrideMode
        | Literal["none"],
        credential_id: UUID | None,
        actor_user_id: UUID | None,
    ) -> None:
        if (mode == "credential") != (credential_id is not None):
            raise CredentialValueError("Credential mode requires a credential ID")
        if credential_id is not None:
            row = await uow.credentials.get_by_id(credential_id)
            if not self._can_select(row, binding, actor_user_id):
                raise NotFoundError("Credential", str(credential_id))

    @staticmethod
    def _can_select(
        row: EncryptedCredential | None,
        binding: _NodeSecretBinding,
        actor_user_id: UUID | None,
    ) -> TypeGuard[EncryptedCredential]:
        if row is None or row.provider_kind != binding.declaration.provider_kind:
            return False
        if row.scope == CredentialScope.SHARED:
            return row.workspace_id == binding.workspace_id
        return actor_user_id is not None and row.owner_user_id == actor_user_id

    def _credential_service(self) -> CredentialService:
        if self._credentials is None:
            raise NodeSecretUnavailableError("The credential vault is unavailable")
        return self._credentials

    async def _load_selection(
        self,
        uow: NodeSecretUnitOfWorkPort,
        binding: _NodeSecretBinding,
        actor_user_id: UUID | None,
    ) -> tuple[
        NodeSharedCredentialBinding | None,
        NodeUserCredentialOverride | None,
        dict[UUID, EncryptedCredential],
    ]:
        if self._credentials is None:
            return None, None, {}
        repo = uow.node_credential_selections
        shared = await repo.get_shared_binding(*binding.key)
        override = None
        if actor_user_id is not None:
            override = await repo.get_user_override(*binding.key, actor_user_id)
        records: dict[UUID, EncryptedCredential] = {}
        for selection in (shared, override):
            if selection is not None and selection.credential_id is not None:
                row = await uow.credentials.get_by_id(selection.credential_id)
                if row is not None:
                    records[row.id] = row
        if (
            actor_user_id is not None
            and shared is not None
            and shared.mode == SharedCredentialBindingMode.PERSONAL
            and (override is None or override.mode == UserCredentialOverrideMode.SHARED)
        ):
            rows = await uow.credentials.list_personal(
                actor_user_id, binding.declaration.provider_kind
            )
            records.update((row.id, row) for row in rows)
        return shared, override, records

    def _selected_record(
        self,
        binding: _NodeSecretBinding,
        shared: NodeSharedCredentialBinding | None,
        override: NodeUserCredentialOverride | None,
        records: Mapping[UUID, EncryptedCredential],
        actor_user_id: UUID | None,
    ) -> EncryptedCredential | Literal["deployment_default"] | None:
        if override is not None:
            if override.mode == UserCredentialOverrideMode.DEPLOYMENT_DEFAULT:
                return "deployment_default"
            if override.mode == UserCredentialOverrideMode.CREDENTIAL:
                record = (
                    records.get(override.credential_id)
                    if override.credential_id
                    else None
                )
                if self._can_select(record, binding, actor_user_id):
                    return record
                raise NodeSecretUnavailableError(
                    "The selected credential is unavailable"
                )
        if shared is None:
            return None
        if shared.mode == SharedCredentialBindingMode.DEPLOYMENT_DEFAULT:
            return "deployment_default"
        if shared.mode == SharedCredentialBindingMode.CREDENTIAL:
            record = records.get(shared.credential_id) if shared.credential_id else None
            if self._can_select(record, binding, None):
                return record
            raise NodeSecretUnavailableError("The shared credential is unavailable")
        credentials = self._credential_service()
        personal = [
            record
            for record in records.values()
            if record.scope == CredentialScope.PERSONAL
            and self._can_select(record, binding, actor_user_id)
            and credentials.usable(record)
        ]
        if len(personal) == 1:
            return personal[0]
        if not personal:
            raise NodeSecretUnavailableError("This node requires a personal credential")
        raise NodeSecretUnavailableError(
            "Multiple personal credentials exist; select one for this node"
        )

    def _state(
        self,
        binding: _NodeSecretBinding,
        inline: EncryptedNodeSecret | None,
        shared: NodeSharedCredentialBinding | None,
        override: NodeUserCredentialOverride | None,
        records: Mapping[UUID, EncryptedCredential],
        actor_user_id: UUID | None,
    ) -> NodeSecretState:
        default_available = (
            self._deployment_default(
                binding.operator_id,
                binding.name,
                binding.dependencies,
            )
            is not None
        )
        shared_record = (
            records.get(shared.credential_id)
            if shared and shared.credential_id
            else None
        )
        if not self._can_select(shared_record, binding, None):
            shared_record = None
        override_record = (
            records.get(override.credential_id)
            if override and override.credential_id
            else None
        )
        if not self._can_select(override_record, binding, actor_user_id):
            override_record = None
        source: NodeSecretSource = "none"
        effective: EncryptedCredential | None = None
        try:
            choice = self._selected_record(
                binding, shared, override, records, actor_user_id
            )
            if isinstance(choice, EncryptedCredential):
                self._credential_service().unseal_record(
                    choice, dependencies=binding.dependencies
                )
                effective = choice
                source = (
                    "personal_credential"
                    if choice.scope == CredentialScope.PERSONAL
                    else "shared_credential"
                )
            elif (
                choice is None
                and inline is not None
                and self._legacy_matches(binding, inline)
            ):
                self._unseal_legacy(binding, inline)
                source = "inline_legacy"
            elif default_available:
                source = "deployment_default"
        except NodeSecretUnavailableError:
            pass
        return NodeSecretState(
            node_id=binding.node_id,
            name=binding.name,
            configured=source != "none",
            provider_kind=binding.declaration.provider_kind,
            effective_source=source,
            effective_credential_id=effective.id if effective else None,
            effective_credential_label=effective.label if effective else None,
            effective_verification_status=effective.verification_status
            if effective
            else None,
            shared_binding_mode=shared.mode if shared else "none",
            shared_credential_id=shared_record.id if shared_record else None,
            shared_credential_label=shared_record.label if shared_record else None,
            shared_credential_missing=shared is not None
            and shared.mode == "credential"
            and shared_record is None,
            personal_override_mode=override.mode if override else "none",
            personal_credential_id=override_record.id if override_record else None,
            personal_credential_label=override_record.label
            if override_record
            else None,
            deployment_default_available=default_available,
            supports_verification=binding.declaration.verifier is not None,
        )

    async def _resolve_binding(
        self,
        uow: NodeSecretUnitOfWorkPort,
        binding: _NodeSecretBinding,
        actor_user_id: UUID | None,
    ) -> SecretStr:
        shared, override, records = await self._load_selection(
            uow, binding, actor_user_id
        )
        selected = self._selected_record(
            binding, shared, override, records, actor_user_id
        )
        if isinstance(selected, EncryptedCredential):
            return self._credential_service().unseal_record(
                selected, dependencies=binding.dependencies
            )
        if selected is None:
            record = await self._legacy_record(uow, binding)
            if record is not None:
                return self._unseal_legacy(binding, record)
        return self._required_default(binding)

    def _required_default(self, binding: _NodeSecretBinding) -> SecretStr:
        default = self._deployment_default(
            binding.operator_id, binding.name, binding.dependencies
        )
        if default is None:
            raise NodeSecretUnavailableError("Required node secret is not configured")
        return default

    def _legacy_matches(
        self, binding: _NodeSecretBinding, record: EncryptedNodeSecret
    ) -> bool:
        return (
            record.operator_id == binding.operator_id
            and record.operator_version == binding.operator_version
            and record.dependency_sha256
            == node_secret_dependency_sha256(
                self._legacy_encryption_binding(binding, record).dependencies
            )
            and record.key_id == self._active_key_id()
        )

    @staticmethod
    def _legacy_encryption_binding(
        binding: _NodeSecretBinding,
        record: EncryptedNodeSecret,
    ) -> _NodeSecretBinding:
        # Older Label Studio inline tokens were sealed before its URL was
        # declared as a dependency. Preserve the original AAD for those rows.
        if (
            binding.declaration.provider_kind == "label_studio"
            and record.dependency_sha256 == node_secret_dependency_sha256({})
        ):
            return replace(binding, dependencies={})
        return binding

    async def _legacy_record(
        self,
        uow: NodeSecretUnitOfWorkPort,
        binding: _NodeSecretBinding,
    ) -> EncryptedNodeSecret | None:
        record = await uow.node_secrets.get(*binding.key)
        if record is None or self._legacy_matches(binding, record):
            return record
        if (
            self._deployment_default(
                binding.operator_id, binding.name, binding.dependencies
            )
            is None
        ):
            if record.key_id != self._active_key_id():
                raise NodeSecretUnavailableError(
                    "Configured node secret cannot be decrypted by this server"
                )
            raise NodeSecretUnavailableError(
                "Configured node secret does not match the saved node configuration"
            )
        return None

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
        actor_user_id: UUID | None = None,
    ) -> SecretStr:
        async with self._uow_factory() as uow:
            binding = await self._validated_binding(
                uow, workspace_id, project_id, graph_id, node_id, name, dependencies
            )
            return await self._resolve_binding(uow, binding, actor_user_id)

    def _unseal_legacy(
        self, binding: _NodeSecretBinding, encrypted: EncryptedNodeSecret
    ) -> SecretStr:
        key, key_id = self._resolved_encryption_key()
        if encrypted.key_id != key_id:
            raise NodeSecretUnavailableError(
                "Configured node secret cannot be decrypted by this server"
            )
        try:
            aad = self._additional_authenticated_data(
                self._legacy_encryption_binding(binding, encrypted),
                encrypted.aad_version,
            )
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
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        async with self._uow_factory() as uow:
            binding = await self._validated_binding(
                uow, workspace_id, project_id, graph_id, node_id, name, dependencies
            )
            if self._credentials is not None:
                shared = await uow.node_credential_selections.get_shared_binding(
                    *binding.key
                )
                if shared is not None:
                    if shared.mode == SharedCredentialBindingMode.PERSONAL:
                        return "mode:personal"
                    if shared.mode == SharedCredentialBindingMode.CREDENTIAL:
                        record = (
                            await uow.credentials.get_by_id(shared.credential_id)
                            if shared.credential_id
                            else None
                        )
                        if not self._can_select(record, binding, None):
                            raise NodeSecretUnavailableError(
                                "The shared credential is unavailable"
                            )
                        self._credentials.unseal_record(
                            record, dependencies=binding.dependencies
                        )
                        return f"shared:{record.cache_revision()}"
                    return self._default_revision(binding)
            encrypted = await self._legacy_record(uow, binding)
            return (
                encrypted.cache_revision()
                if encrypted
                else self._default_revision(binding)
            )

    def _default_revision(self, binding: _NodeSecretBinding) -> str:
        default = self._required_default(binding)
        identity = json.dumps(
            [
                binding.operator_id,
                binding.name,
                binding.dependencies,
                default.get_secret_value(),
            ],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"default:{sha256(identity).hexdigest()}"

    async def _validated_binding(
        self,
        uow: NodeSecretUnitOfWorkPort,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> _NodeSecretBinding:
        if project_id is None or graph_id is None or node_id is None:
            raise NodeSecretUnavailableError(
                "A Project and Graph context is required to resolve a node secret"
            )
        head = await self._head(uow, workspace_id, project_id)
        binding = await self._binding(head, graph_id, node_id, name)
        try:
            matches = canonical_node_secret_dependencies(
                dependencies
            ) == canonical_node_secret_dependencies(binding.dependencies)
        except InvalidNodeSecretDependenciesError as exc:
            raise NodeSecretUnavailableError(
                "Node secret dependencies must be canonical JSON values"
            ) from exc
        if not matches:
            raise NodeSecretUnavailableError(
                "Configured node secret does not match the saved node configuration"
            )
        return binding

    def _deployment_default(
        self, operator_id: str, name: str, dependencies: Mapping[str, JsonValue]
    ) -> SecretStr | None:
        if name != "api_key":
            return None
        config = self._provider_secrets
        if operator_id == "reducto.ocr.provider":
            key = config.reducto_api_key
        elif operator_id == "mistral.ocr.provider":
            key = config.mistral_api_key
        elif operator_id == "llm.openai_compatible.chat_completion":
            endpoint = dependencies.get("base_url")
            if config.openai_base_url is None or not isinstance(endpoint, str):
                return None
            try:
                parsed = TypeAdapter(AnyHttpUrl).validate_python(endpoint)
            except ValidationError:
                return None
            if str(parsed).rstrip("/") != str(config.openai_base_url).rstrip("/"):
                return None
            key = config.openai_api_key
        else:
            return None
        if key is None or not key.get_secret_value().strip():
            return None
        return key

    @staticmethod
    async def _head(
        unit_of_work: NodeSecretUnitOfWorkPort,
        workspace_id: UUID,
        project_id: UUID,
        *,
        lock: bool = False,
    ) -> ProjectHead:
        repository = unit_of_work.collaboration
        head = await (
            repository.lock_head(workspace_id, project_id)
            if lock
            else repository.get_head(workspace_id, project_id)
        )
        if head is None:
            raise NotFoundError("Project", str(project_id))
        return head

    @staticmethod
    def _graph(head: ProjectHead, graph_id: str) -> GraphDefinition:
        try:
            return head.document.get_graph(graph_id)
        except ProjectDocumentError as exc:
            raise NotFoundError("Graph", graph_id) from exc

    async def _binding(
        self,
        head: ProjectHead,
        graph_id: str,
        node_id: str,
        name: str,
    ) -> _NodeSecretBinding:
        graph = self._graph(head, graph_id)
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
        contract = await self._resolved_node_secret_contract(node)
        if contract is None:
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
            workspace_id=head.workspace_id,
            project_id=head.project_id,
            graph_id=graph.id,
            node_id=node.id,
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            declaration=declaration,
            dependencies=self._declared_dependencies(
                declaration,
                contract.config,
            ),
        )

    async def _resolved_node_secret_contract(
        self,
        node: GraphNode,
    ) -> _ResolvedNodeSecretContract | None:
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
        declaration: NodeSecretInput,
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
        if aad_version != 3:
            raise ValueError("Unsupported node secret AAD version")
        identity["workspace_id"] = str(binding.workspace_id)
        identity["project_id"] = str(binding.project_id)
        return json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _resolved_encryption_key(self) -> tuple[bytes, str]:
        try:
            return resolve_credential_encryption_key(self._encryption_key)
        except CredentialKeyConfigurationError as exc:
            raise NodeSecretConfigurationError(str(exc)) from exc

    def _active_key_id(self) -> str | None:
        try:
            _, key_id = self._resolved_encryption_key()
        except NodeSecretConfigurationError:
            return None
        return key_id
