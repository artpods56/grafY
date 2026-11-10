"""Single-use OIDC login transactions and their encrypted PKCE verifiers."""

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
from secrets import token_bytes
from typing import NoReturn
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from grafy_core.domain.identity import OidcLoginTransaction
from grafy_core.ports.identity import IdentityUnitOfWorkPort
from grafy_shared.config import AuthConfig

from grafy_api.auth.errors import (
    OidcProtocolError,
    require_config_value,
    require_oidc_configuration,
)
from grafy_api.auth.secrets import digest_secret


class LoginTransactions:
    """Lock, validate, and consume the server record for one login attempt."""

    def __init__(self, auth: AuthConfig) -> None:
        self._auth = auth

    def require_configured(self) -> None:
        require_oidc_configuration(self._auth.oidc_is_configured)

    def validate_return_path(self, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or "\x00" in value
            or "\\" in value
        ):
            raise OidcProtocolError("invalid_return_path")
        return value

    def parse_transaction_id(self, value: str | None) -> UUID:
        if value is None:
            raise OidcProtocolError("missing_login_transaction")
        try:
            return UUID(value)
        except ValueError as exc:
            raise OidcProtocolError("invalid_login_transaction") from exc

    def encrypt_verifier(self, verifier: str, transaction_id: UUID) -> bytes:
        nonce = token_bytes(12)
        ciphertext = ChaCha20Poly1305(self.wrapping_key()).encrypt(
            nonce,
            verifier.encode("ascii"),
            transaction_id.bytes,
        )
        return nonce + ciphertext

    def decrypt_verifier(self, transaction: OidcLoginTransaction) -> str:
        if transaction.pkce_key_version != self._auth.oidc_auth_wrapping_key_version:
            raise OidcProtocolError("unsupported_key_version")
        encrypted = transaction.encrypted_pkce_verifier
        try:
            plaintext = ChaCha20Poly1305(self.wrapping_key()).decrypt(
                encrypted[:12],
                encrypted[12:],
                transaction.id.bytes,
            )
            return plaintext.decode("ascii")
        except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
            raise OidcProtocolError("invalid_pkce_verifier") from exc

    def wrapping_key(self) -> bytes:
        self.require_configured()
        configured_key = self._auth.oidc_auth_wrapping_key
        if configured_key is None:
            raise OidcProtocolError("oidc_not_configured")
        return hashlib.sha256(configured_key.get_secret_value().encode()).digest()

    def client_id(self) -> str:
        return require_config_value(self._auth.oidc_client_id)

    async def replace(
        self,
        unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
        value: str | None,
    ) -> UUID | None:
        if value is None:
            return None
        try:
            transaction_id = UUID(value)
        except ValueError:
            return None
        async with unit_of_work_factory() as unit_of_work:
            transaction = await self._lock_live(unit_of_work, transaction_id)
            if transaction is None:
                return None
            await self._consume(unit_of_work, transaction)
            return transaction_id

    async def consume_for_callback(
        self,
        unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
        *,
        transaction_id: UUID,
        state: str,
    ) -> tuple[OidcLoginTransaction, str, str]:
        async with unit_of_work_factory() as unit_of_work:
            transaction = await self._lock_live(unit_of_work, transaction_id)
            if transaction is None:
                raise OidcProtocolError("invalid_login_transaction")
            if transaction.expires_at <= datetime.now(UTC):
                await self._reject(unit_of_work, transaction, "expired_login_transaction")
            if not hmac.compare_digest(transaction.state_digest, digest_secret(state)):
                await self._reject(unit_of_work, transaction, "invalid_state")
            try:
                verifier = self.decrypt_verifier(transaction)
            except OidcProtocolError:
                await self._reject(unit_of_work, transaction, "invalid_pkce_verifier")
            await self._consume(unit_of_work, transaction)
            return transaction, verifier, transaction.return_path

    async def consume_for_failure(
        self,
        unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
        transaction_id: UUID,
        *,
        state: str | None,
    ) -> bool:
        async with unit_of_work_factory() as unit_of_work:
            transaction = await self._lock_live(unit_of_work, transaction_id)
            if transaction is None:
                return False
            state_rejected = state is not None and not hmac.compare_digest(
                transaction.state_digest,
                digest_secret(state),
            )
            await self._consume(unit_of_work, transaction)
            if state_rejected:
                raise OidcProtocolError("invalid_state", transaction_consumed=True)
            return True

    async def _lock_live(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        transaction_id: UUID,
    ) -> OidcLoginTransaction | None:
        transaction = await unit_of_work.identity.lock_login_transaction(transaction_id)
        if transaction is None or transaction.is_consumed:
            return None
        return transaction

    async def _consume(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        transaction: OidcLoginTransaction,
    ) -> None:
        transaction.consume()
        await unit_of_work.commit()

    async def _reject(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        transaction: OidcLoginTransaction,
        code: str,
    ) -> NoReturn:
        await self._consume(unit_of_work, transaction)
        raise OidcProtocolError(code, transaction_consumed=True)
