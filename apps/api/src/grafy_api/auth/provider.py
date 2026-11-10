"""OpenID Connect discovery, key fetch, and ID token validation.

An unexpired cache is returned before any network call. A failed refresh does
not serve that cache: the caller already returned it while it was fresh, and a
provider outage after expiry fails closed.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import math
from typing import Any, cast

from authlib.jose import JsonWebToken, JoseError
import httpx

from grafy_shared.config import AuthConfig

from grafy_api.auth.errors import OidcProtocolError, require_config_value
from grafy_api.auth.secrets import digest_secret


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class OidcProvider:
    """The configured issuer's discovery document, JWKS, and token endpoint."""

    def __init__(self, auth: AuthConfig, *, callback_url: str) -> None:
        self._auth = auth
        self._callback_url = callback_url
        self._metadata: ProviderMetadata | None = None
        self._metadata_expires_at: datetime | None = None
        self._jwks: dict[str, object] | list[object] | None = None
        self._jwks_expires_at: datetime | None = None

    async def discover(self) -> ProviderMetadata:
        now = datetime.now(UTC)
        if (
            self._metadata is not None
            and self._metadata_expires_at is not None
            and self._metadata_expires_at > now
        ):
            return self._metadata
        issuer = require_config_value(self._auth.oidc_issuer)
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(discovery_url)
            response.raise_for_status()
            raw_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcProtocolError("provider_discovery_unavailable") from exc
        if not isinstance(raw_payload, dict):
            raise OidcProtocolError("invalid_provider_metadata")
        payload = cast(dict[str, object], raw_payload)
        if payload.get("issuer") != issuer:
            raise OidcProtocolError("provider_issuer_mismatch")
        authorization_endpoint = payload.get("authorization_endpoint")
        token_endpoint = payload.get("token_endpoint")
        jwks_uri = payload.get("jwks_uri")
        if not all(
            isinstance(value, str)
            for value in (authorization_endpoint, token_endpoint, jwks_uri)
        ):
            raise OidcProtocolError("invalid_provider_metadata")
        metadata = ProviderMetadata(
            issuer=issuer,
            authorization_endpoint=cast(str, authorization_endpoint),
            token_endpoint=cast(str, token_endpoint),
            jwks_uri=cast(str, jwks_uri),
        )
        self._metadata = metadata
        self._metadata_expires_at = now + timedelta(minutes=5)
        return metadata

    async def keys(
        self, *, force_refresh: bool = False
    ) -> dict[str, object] | list[object]:
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._jwks is not None
            and self._jwks_expires_at is not None
            and self._jwks_expires_at > now
        ):
            return self._jwks
        metadata = await self.discover()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(metadata.jwks_uri)
            response.raise_for_status()
            raw_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcProtocolError("provider_keys_unavailable") from exc
        if not isinstance(raw_payload, (dict, list)):
            raise OidcProtocolError("invalid_provider_keys")
        payload = cast(dict[str, object] | list[object], raw_payload)
        self._jwks = payload
        self._jwks_expires_at = now + timedelta(minutes=5)
        return payload

    async def exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        nonce_digest: bytes,
    ) -> dict[str, object]:
        metadata = await self.discover()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._callback_url,
            "client_id": require_config_value(self._auth.oidc_client_id),
            "code_verifier": verifier,
        }
        if self._auth.oidc_client_secret is not None:
            data["client_secret"] = self._auth.oidc_client_secret.get_secret_value()
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(metadata.token_endpoint, data=data)
        if response.status_code != 200:
            raise OidcProtocolError("provider_token_exchange_failed")
        try:
            raw_payload = response.json()
        except (TypeError, ValueError) as exc:
            raise OidcProtocolError("invalid_token_response") from exc
        if not isinstance(raw_payload, dict):
            raise OidcProtocolError("missing_id_token")
        payload = cast(dict[str, object], raw_payload)
        id_token = payload.get("id_token")
        if not isinstance(id_token, str):
            raise OidcProtocolError("missing_id_token")
        return await self.validate_id_token(id_token, nonce_digest=nonce_digest)

    async def validate_id_token(
        self,
        encoded: str,
        *,
        nonce_digest: bytes,
    ) -> dict[str, object]:
        jwks = await self.keys()
        decoder: Any = JsonWebToken(self._auth.oidc_allowed_signing_algorithms)
        try:
            claims = decoder.decode(encoded, cast(Any, jwks))
        except (JoseError, ValueError, TypeError):
            try:
                refreshed_jwks = await self.keys(force_refresh=True)
                claims = decoder.decode(encoded, cast(Any, refreshed_jwks))
            except (JoseError, OidcProtocolError, ValueError, TypeError) as refresh_exc:
                raise OidcProtocolError("invalid_id_token") from refresh_exc
        try:
            claims.validate(leeway=60)
        except (JoseError, ValueError, TypeError) as exc:
            raise OidcProtocolError("invalid_id_token") from exc
        values = cast(dict[str, object], dict(claims))
        issuer = require_config_value(self._auth.oidc_issuer)
        if values.get("iss") != issuer:
            raise OidcProtocolError("invalid_issuer")
        audience = values.get("aud")
        client_id = require_config_value(self._auth.oidc_client_id)
        if isinstance(audience, str):
            audiences = [audience]
        elif isinstance(audience, list):
            audience_values = cast(list[object], audience)
            audiences = [item for item in audience_values if isinstance(item, str)]
            if len(audiences) != len(audience_values):
                raise OidcProtocolError("invalid_audience")
        else:
            raise OidcProtocolError("invalid_audience")
        if client_id not in audiences:
            raise OidcProtocolError("invalid_audience")
        authorized_party = values.get("azp")
        if authorized_party is not None and authorized_party != client_id:
            raise OidcProtocolError("invalid_authorized_party")
        if len(audiences) > 1 and authorized_party != client_id:
            raise OidcProtocolError("missing_authorized_party")
        if not isinstance(values.get("sub"), str):
            raise OidcProtocolError("missing_subject")
        nonce = values.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise OidcProtocolError("missing_nonce")
        if not hmac.compare_digest(nonce_digest, digest_secret(nonce)):
            raise OidcProtocolError("invalid_nonce")
        # exp and iat are required finite numbers even when the library's
        # validate() only checks the claims that happen to be present.
        for claim in ("exp", "iat"):
            claim_value = values.get(claim)
            if (
                isinstance(claim_value, bool)
                or not isinstance(claim_value, (int, float))
                or not math.isfinite(claim_value)
            ):
                raise OidcProtocolError(f"missing_{claim}")
        now = datetime.now(UTC).timestamp()
        exp = cast(float, values["exp"])
        issued_at = cast(float, values["iat"])
        if exp <= now - 60:
            raise OidcProtocolError("expired_id_token")
        if issued_at > now + 60:
            raise OidcProtocolError("future_id_token")
        not_before = values.get("nbf")
        if not_before is not None and (
            isinstance(not_before, bool)
            or not isinstance(not_before, (int, float))
            or not math.isfinite(not_before)
            or not_before > now + 60
        ):
            raise OidcProtocolError("future_id_token")
        return values


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
