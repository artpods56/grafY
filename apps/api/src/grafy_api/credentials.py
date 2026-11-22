import json
import os
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import NotRequired, TypedDict, Unpack, cast
from uuid import UUID, uuid4

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from grafy_core.credential_verification import (
    EGRESS_BLOCKED,
    UNREACHABLE,
    verification_endpoint,
)
from grafy_core.domain.credentials import (
    CredentialScope,
    CredentialVerificationResult,
    EncryptedCredential,
)
from grafy_core.domain.credentials import (
    CredentialVerificationStatus as Status,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.node_secrets import JsonValue, canonical_node_secret_dependencies
from grafy_core.egress import (
    EgressPolicy,
    EgressRejectedError,
    PinnedPublicAddressTransport,
)
from grafy_core.plugins import CredentialVerifier, PluginRegistry
from grafy_core.ports.node_secrets import (
    NodeSecretUnavailableError,
    NodeSecretUnitOfWorkPort,
)
from pydantic import SecretStr

from grafy_api.credential_keys import (
    MAX_SEALED_CREDENTIAL_BYTES,
    CredentialKeyConfigurationError,
    resolve_credential_encryption_key,
)


class CredentialValueError(ValueError):
    pass


class CredentialRateLimitError(RuntimeError):
    pass


class CredentialChangedError(RuntimeError):
    pass


class CredentialVerificationFailedError(ValueError):
    def __init__(self, result: CredentialVerificationResult) -> None:
        super().__init__(result.message)
        self.result = result
        self.can_save_unverified = result.status in {
            Status.UNREACHABLE,
            Status.UNSUPPORTED,
        }


@dataclass(frozen=True, slots=True)
class CredentialView:
    id: UUID
    scope: CredentialScope
    provider_kind: str
    label: str
    key_hint: str | None
    usable: bool
    supports_verification: bool
    verification_status: Status
    verification_message: str | None
    verification_hint: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class _VerificationOptions(TypedDict, total=False):
    verify: bool
    save_if_unverified: bool
    verify_config: Mapping[str, JsonValue] | None


class _CreateOptions(_VerificationOptions):
    provider_kind: str
    label: str
    value: SecretStr


class _UpdateOptions(_VerificationOptions):
    label: NotRequired[str | None]
    value: NotRequired[SecretStr | None]


class CredentialService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], NodeSecretUnitOfWorkPort],
        plugin_registry: PluginRegistry,
        encryption_key: SecretStr | None,
        egress_policy: EgressPolicy | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        verify_limit: int = 20,
        verify_window_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._uow_factory = unit_of_work_factory
        self._encryption_key = encryption_key
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(
                transport=PinnedPublicAddressTransport(policy=egress_policy),
                timeout=httpx.Timeout(8.0),
                follow_redirects=False,
                trust_env=False,
            )
        )
        self._verifiers: dict[str, CredentialVerifier | None] = {}
        self._dependencies: dict[str, set[str]] = {}
        for node in plugin_registry.nodes:
            for declaration in node.secret_inputs:
                kind = declaration.provider_kind
                self._dependencies.setdefault(kind, set()).update(
                    declaration.config_dependencies
                )
                if declaration.verifier is not None or kind not in self._verifiers:
                    self._verifiers[kind] = declaration.verifier
        self._verify_limit = verify_limit
        self._verify_window = verify_window_seconds
        self._clock = clock
        self._verify_calls: deque[tuple[float, UUID]] = deque()
        self._verify_counts: dict[UUID, int] = {}

    def check_verify_rate(self, user_id: UUID) -> None:
        now = self._clock()
        while (
            self._verify_calls and self._verify_calls[0][0] <= now - self._verify_window
        ):
            _, expired_user = self._verify_calls.popleft()
            remaining = self._verify_counts[expired_user] - 1
            if remaining:
                self._verify_counts[expired_user] = remaining
            else:
                del self._verify_counts[expired_user]
        count = self._verify_counts.get(user_id, 0)
        if count >= self._verify_limit:
            raise CredentialRateLimitError("Verification rate limit exceeded")
        self._verify_counts[user_id] = count + 1
        self._verify_calls.append((now, user_id))

    def supports_verification(self, provider_kind: str) -> bool:
        return self._verifiers.get(provider_kind) is not None

    def _check_provider(self, provider_kind: str) -> None:
        if provider_kind not in self._verifiers:
            raise CredentialValueError("Unknown credential provider kind")

    async def verify_candidate(
        self,
        *,
        provider_kind: str,
        value: SecretStr,
        config: Mapping[str, JsonValue] | None = None,
    ) -> CredentialVerificationResult:
        self._check_provider(provider_kind)
        raw = self._plaintext(value)
        verifier = self._verifiers[provider_kind]
        if verifier is None:
            return CredentialVerificationResult(
                Status.UNSUPPORTED, "This provider has no verification callback."
            )
        try:
            async with self._http_client_factory() as client:
                result = await verifier(value, config or {}, client)
        except EgressRejectedError:
            return EGRESS_BLOCKED
        except Exception:
            # Provider clients may embed the request or its credentials in their exceptions.
            return UNREACHABLE

        message = result.message
        hint = result.account_hint
        if raw in message or not message.isprintable():
            message = {
                Status.VALID: "Credential verified.",
                Status.INVALID: "Provider rejected the credential.",
            }.get(result.status, "Credential verification completed.")
        if hint is not None and (raw in hint or not hint.isprintable()):
            hint = None
        return CredentialVerificationResult(result.status, message, hint)

    async def list_personal(
        self, user_id: UUID, provider_kind: str | None = None
    ) -> list[CredentialView]:
        async with self._uow_factory() as uow:
            return [
                self._view(row)
                for row in await uow.credentials.list_personal(user_id, provider_kind)
            ]

    async def list_shared(
        self, workspace_id: UUID, provider_kind: str | None = None
    ) -> list[CredentialView]:
        async with self._uow_factory() as uow:
            return [
                self._view(row)
                for row in await uow.credentials.list_shared(
                    workspace_id, provider_kind
                )
            ]

    async def create_personal(
        self, *, user_id: UUID, **options: Unpack[_CreateOptions]
    ) -> CredentialView:
        return await self._create(
            owner_user_id=user_id,
            workspace_id=None,
            created_by_user_id=user_id,
            **options,
        )

    async def create_shared(
        self,
        *,
        workspace_id: UUID,
        created_by_user_id: UUID,
        **options: Unpack[_CreateOptions],
    ) -> CredentialView:
        return await self._create(
            owner_user_id=None,
            workspace_id=workspace_id,
            created_by_user_id=created_by_user_id,
            **options,
        )

    async def update_personal(
        self, *, user_id: UUID, credential_id: UUID, **options: Unpack[_UpdateOptions]
    ) -> CredentialView:
        return await self._update(
            CredentialScope.PERSONAL, user_id, credential_id, **options
        )

    async def update_shared(
        self,
        *,
        workspace_id: UUID,
        credential_id: UUID,
        **options: Unpack[_UpdateOptions],
    ) -> CredentialView:
        return await self._update(
            CredentialScope.SHARED, workspace_id, credential_id, **options
        )

    async def verify_saved_personal(
        self,
        *,
        user_id: UUID,
        credential_id: UUID,
        config: Mapping[str, JsonValue] | None = None,
    ) -> CredentialView:
        return await self._verify_saved(
            CredentialScope.PERSONAL, user_id, credential_id, config
        )

    async def verify_saved_shared(
        self,
        *,
        workspace_id: UUID,
        credential_id: UUID,
        config: Mapping[str, JsonValue] | None = None,
    ) -> CredentialView:
        return await self._verify_saved(
            CredentialScope.SHARED, workspace_id, credential_id, config
        )

    async def delete_personal(self, user_id: UUID, credential_id: UUID) -> None:
        await self._delete(CredentialScope.PERSONAL, user_id, credential_id)

    async def delete_shared(self, workspace_id: UUID, credential_id: UUID) -> None:
        await self._delete(CredentialScope.SHARED, workspace_id, credential_id)

    async def _create(
        self,
        *,
        owner_user_id: UUID | None,
        workspace_id: UUID | None,
        created_by_user_id: UUID,
        provider_kind: str,
        label: str,
        value: SecretStr,
        verify: bool = True,
        save_if_unverified: bool = False,
        verify_config: Mapping[str, JsonValue] | None = None,
    ) -> CredentialView:
        self._check_provider(provider_kind)
        label = self._label(label)
        raw = self._plaintext(value)
        config = self._bound_config(provider_kind, verify_config or {})
        key, key_id = resolve_credential_encryption_key(self._encryption_key)
        result = await self._verify_for_save(
            provider_kind, value, config, verify, save_if_unverified
        )
        now = datetime.now(UTC)
        credential_id = uuid4()
        scope = (
            CredentialScope.PERSONAL
            if owner_user_id is not None
            else CredentialScope.SHARED
        )
        aad = self._aad(
            credential_id, scope, owner_user_id, workspace_id, provider_kind
        )
        nonce, ciphertext = self._seal(key, aad, raw, config)
        record = EncryptedCredential(
            id=credential_id,
            scope=scope,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            provider_kind=provider_kind,
            label=label,
            key_hint=self._hint(raw),
            key_id=key_id,
            aad_version=1,
            nonce=nonce,
            ciphertext=ciphertext,
            verification_status=result.status if result else Status.UNVERIFIED,
            verification_message=result.message if result else None,
            verification_hint=result.account_hint if result else None,
            verified_at=now if result else None,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.credentials.insert(record)
            await uow.commit()
        return self._view(record)

    async def _update(
        self,
        scope: CredentialScope,
        owner_id: UUID,
        credential_id: UUID,
        *,
        label: str | None = None,
        value: SecretStr | None = None,
        verify: bool = True,
        save_if_unverified: bool = False,
        verify_config: Mapping[str, JsonValue] | None = None,
    ) -> CredentialView:
        async with self._uow_factory() as uow:
            record = await self._owned(uow, scope, owner_id, credential_id)
        renamed = self._label(label) if label is not None else record.label
        updated = replace(record, label=renamed)
        if value is not None:
            raw = self._plaintext(value)
            key, key_id = resolve_credential_encryption_key(self._encryption_key)
            config = verify_config
            if config is None and self.usable(record):
                _, config = self._unseal(record)
            bound_config = self._bound_config(record.provider_kind, config or {})
            result = await self._verify_for_save(
                record.provider_kind, value, bound_config, verify, save_if_unverified
            )
            nonce, ciphertext = self._seal(
                key, self._record_aad(record), raw, bound_config
            )
            updated = replace(
                updated,
                key_id=key_id,
                key_hint=self._hint(raw),
                nonce=nonce,
                ciphertext=ciphertext,
                verification_status=result.status if result else Status.UNVERIFIED,
                verification_message=result.message if result else None,
                verification_hint=result.account_hint if result else None,
                verified_at=datetime.now(UTC) if result else None,
            )
        return await self._save_update(record, updated)

    async def _save_update(
        self, previous: EncryptedCredential, updated: EncryptedCredential
    ) -> CredentialView:
        updated = replace(updated, updated_at=datetime.now(UTC))
        async with self._uow_factory() as uow:
            if not await uow.credentials.update(
                updated, expected_updated_at=previous.updated_at
            ):
                raise CredentialChangedError(
                    "Credential changed. Reload it and try again."
                )
            await uow.commit()
        return self._view(updated)

    async def _verify_saved(
        self,
        scope: CredentialScope,
        owner_id: UUID,
        credential_id: UUID,
        config: Mapping[str, JsonValue] | None,
    ) -> CredentialView:
        async with self._uow_factory() as uow:
            record = await self._owned(uow, scope, owner_id, credential_id)
        value, saved_config = self._unseal(record)
        if config and self._bound_config(record.provider_kind, config) != saved_config:
            raise CredentialValueError(
                "Verification settings must match the saved credential"
            )
        result = await self.verify_candidate(
            provider_kind=record.provider_kind, value=value, config=saved_config
        )
        return await self._save_update(
            record,
            replace(
                record,
                verification_status=result.status,
                verification_message=result.message,
                verification_hint=result.account_hint,
                verified_at=datetime.now(UTC),
            ),
        )

    async def _delete(
        self, scope: CredentialScope, owner_id: UUID, credential_id: UUID
    ) -> None:
        async with self._uow_factory() as uow:
            await self._owned(uow, scope, owner_id, credential_id)
            await uow.credentials.delete(credential_id)
            await uow.commit()

    @staticmethod
    async def _owned(
        uow: NodeSecretUnitOfWorkPort,
        scope: CredentialScope,
        owner_id: UUID,
        credential_id: UUID,
    ) -> EncryptedCredential:
        row = await uow.credentials.get_by_id(credential_id)
        if row is not None and row.scope == scope:
            row_owner = (
                row.owner_user_id
                if scope == CredentialScope.PERSONAL
                else row.workspace_id
            )
            if row_owner == owner_id:
                return row
        raise NotFoundError("Credential", str(credential_id))

    async def _verify_for_save(
        self,
        provider_kind: str,
        value: SecretStr,
        config: Mapping[str, JsonValue],
        verify: bool,
        save_if_unverified: bool,
    ) -> CredentialVerificationResult | None:
        if not verify:
            return None
        result = await self.verify_candidate(
            provider_kind=provider_kind, value=value, config=config
        )
        failure = CredentialVerificationFailedError(result)
        if result.status != Status.VALID and not (
            failure.can_save_unverified and save_if_unverified
        ):
            raise failure
        return result

    @staticmethod
    def _plaintext(value: SecretStr) -> str:
        raw = value.get_secret_value()
        try:
            size = len(raw.encode("utf-8"))
        except UnicodeEncodeError:
            raise CredentialValueError("Credential value is not valid UTF-8") from None
        if not raw.strip() or size > MAX_SEALED_CREDENTIAL_BYTES:
            raise CredentialValueError(
                "Credential value must contain 1 to 65536 UTF-8 bytes"
            )
        return raw

    @staticmethod
    def _label(value: str) -> str:
        label = value.strip()
        if not label or len(label) > 160:
            raise CredentialValueError(
                "Credential label must contain 1 to 160 characters"
            )
        return label

    @staticmethod
    def _hint(raw: str) -> str | None:
        return f"••••{raw[-4:]}" if len(raw) >= 8 else None

    @staticmethod
    def _aad(
        credential_id: UUID,
        scope: CredentialScope,
        owner_user_id: UUID | None,
        workspace_id: UUID | None,
        provider_kind: str,
    ) -> bytes:
        return canonical_node_secret_dependencies(
            {
                "version": 1,
                "id": str(credential_id),
                "scope": scope.value,
                "owner_user_id": str(owner_user_id) if owner_user_id else None,
                "workspace_id": str(workspace_id) if workspace_id else None,
                "provider_kind": provider_kind,
            }
        )

    def _record_aad(self, record: EncryptedCredential) -> bytes:
        return self._aad(
            record.id,
            record.scope,
            record.owner_user_id,
            record.workspace_id,
            record.provider_kind,
        )

    def _bound_config(
        self, provider_kind: str, config: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        # Authorize the endpoint at vault write time. Graph editors can select a
        # shared key but must never be able to change where a bearer key is sent.
        bound: dict[str, JsonValue] = {}
        for field in self._dependencies.get(provider_kind, ()):
            value = config.get(field)
            if (
                field == "base_url"
                and value is None
                and provider_kind == "openai_compatible"
            ):
                value = "https://api.openai.com/v1"
            if field.endswith("_url"):
                try:
                    value = verification_endpoint(value)
                except ValueError:
                    raise CredentialValueError(
                        f"Provide a valid {field} for this credential"
                    ) from None
            bound[field] = value
        return bound

    @staticmethod
    def _seal(
        key: bytes, aad: bytes, raw: str, config: Mapping[str, JsonValue]
    ) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        payload = canonical_node_secret_dependencies(
            {"value": raw, "config": dict(config)}
        )
        return nonce, AESGCM(key).encrypt(nonce, payload, aad)

    def _unseal(
        self, record: EncryptedCredential
    ) -> tuple[SecretStr, dict[str, JsonValue]]:
        try:
            key, key_id = resolve_credential_encryption_key(self._encryption_key)
            if record.key_id != key_id or record.aad_version != 1:
                raise ValueError("Wrong key or AAD version")
            raw = AESGCM(key).decrypt(
                record.nonce, record.ciphertext, self._record_aad(record)
            )
            payload = json.loads(raw)
            return SecretStr(payload["value"]), cast(
                dict[str, JsonValue], payload["config"]
            )
        except (
            CredentialKeyConfigurationError,
            InvalidTag,
            ValueError,
            KeyError,
            TypeError,
        ):
            raise NodeSecretUnavailableError(
                "Saved credential cannot be decrypted by this server"
            ) from None

    def unseal_record(
        self,
        record: EncryptedCredential,
        *,
        dependencies: Mapping[str, JsonValue] | None = None,
    ) -> SecretStr:
        value, saved_config = self._unseal(record)
        if dependencies is not None:
            try:
                matches = (
                    self._bound_config(record.provider_kind, dependencies)
                    == saved_config
                )
            except CredentialValueError:
                matches = False
            if not matches:
                raise NodeSecretUnavailableError(
                    "Saved credential does not match the node endpoint"
                )
        return value

    def usable(self, record: EncryptedCredential) -> bool:
        try:
            _, key_id = resolve_credential_encryption_key(self._encryption_key)
        except CredentialKeyConfigurationError:
            return False
        return record.key_id == key_id

    def _view(self, record: EncryptedCredential) -> CredentialView:
        return CredentialView(
            id=record.id,
            scope=record.scope,
            provider_kind=record.provider_kind,
            label=record.label,
            key_hint=record.key_hint,
            usable=self.usable(record),
            supports_verification=self.supports_verification(record.provider_kind),
            verification_status=record.verification_status,
            verification_message=record.verification_message,
            verification_hint=record.verification_hint,
            verified_at=record.verified_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
