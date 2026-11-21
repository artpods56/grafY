"""Signed read grants: the tiler's only input about *what* to read.

The API signs a grant for one stored object after it has checked the caller's
Workspace capability. The tiler never accepts a URL or a path, so the worst a
forged request can do is nothing. Wire format::

    token     = b64url(payload) "." b64url(HMAC-SHA256(key, b64url(payload)))
    payload   = canonical JSON (sorted keys, no spaces) of the fields below

The signature covers the *encoded* payload, so the verifier never has to
re-canonicalise anything and a signer in another language only needs to emit
the same bytes it signs.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Self, cast

GRANT_VERSION: Final = 1
MOSAIC_GRANT_VERSION: Final = 1
MAX_MOSAIC_SOURCES: Final = 64

# Object keys the API writes are relative, slash-separated and printable. This
# is deliberately stricter than S3 so a grant can never smuggle `..` segments,
# a leading slash or control characters into a `/vsis3/` path.
_KEY_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/=+@ ]{0,1023}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
MAX_PAGE: Final = 1023


class GrantError(Exception):
    """The grant is malformed, forged, expired, or names something not allowed."""


@dataclass(frozen=True, slots=True)
class Grant:
    bucket: str
    key: str
    sha256: str
    byte_size: int
    page: int
    expires_at: int

    def sign_grant(self, key: bytes) -> str:
        """Sign a read grant after the caller has authorized access to its source."""
        payload = json.dumps(
            {
                "v": GRANT_VERSION,
                "b": self.bucket,
                "k": self.key,
                "s": self.sha256,
                "n": self.byte_size,
                "p": self.page,
                "exp": self.expires_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = _b64encode(payload.encode("utf-8"))
        return f"{encoded}.{_b64encode(_mac(key, encoded))}"

    @classmethod
    def verify_grant(
        cls,
        token: str,
        *,
        keys: Iterable[bytes],
        bucket: str,
        skew_seconds: int,
        max_source_bytes: int,
        now: int | None = None,
    ) -> Self:
        """Return the grant the token carries, or raise :class:`GrantError`.

        Checks, in order: shape, signature against any configured key (constant
        time), version, expiry, bucket, object key, digest, size and page. A
        failure never says which key or which byte was wrong.
        """
        if now is None:
            now = int(time.time())
        payload = _verified_payload(token, keys)
        # A mosaic grant is signed with the same keys; it must never pass here.
        if payload.get("kind") is not None:
            raise GrantError("unsupported grant kind")

        granted_bucket, object_key = payload.get("b"), payload.get("k")
        sha256, byte_size = payload.get("s"), _integer(payload, "n")
        page, expires_at = _integer(payload, "p"), _integer(payload, "exp")

        if payload.get("v") != GRANT_VERSION:
            raise GrantError("unsupported grant version")

        if now > expires_at + skew_seconds:
            raise GrantError("grant has expired")

        if granted_bucket != bucket:
            raise GrantError("grant names a bucket this tiler does not serve")

        if not isinstance(object_key, str) or not is_safe_key(object_key):
            raise GrantError("grant object key is not allowed")

        if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
            raise GrantError("grant digest is not a SHA-256")

        if byte_size < 1 or byte_size > max_source_bytes:
            raise GrantError("grant object size is out of bounds")

        if not 0 <= page <= MAX_PAGE:
            raise GrantError("grant page is out of bounds")

        return cls(
            bucket=bucket,
            key=object_key,
            sha256=sha256,
            byte_size=byte_size,
            page=page,
            expires_at=expires_at,
        )


@dataclass(frozen=True, slots=True)
class GrantSource:
    key: str
    sha256: str
    byte_size: int
    page: int = 0


@dataclass(frozen=True, slots=True)
class MosaicGrant:
    """Signed multi-source read grant ordered bottom-to-top (painter's order).

    Wire format is the single-source token shape with a payload of
    ``{"v", "kind": "mosaic", "b", "exp", "src": [{"k", "s", "n", "p"}, ...]}``.
    """

    bucket: str
    sources: tuple[GrantSource, ...]
    expires_at: int

    def as_grants(self) -> tuple[Grant, ...]:
        return tuple(
            Grant(
                bucket=self.bucket,
                key=source.key,
                sha256=source.sha256,
                byte_size=source.byte_size,
                page=source.page,
                expires_at=self.expires_at,
            )
            for source in self.sources
        )

    def sign_grant(self, key: bytes) -> str:
        """Sign a mosaic grant after the caller has authorized every source."""
        payload = json.dumps(
            {
                "v": MOSAIC_GRANT_VERSION,
                "kind": "mosaic",
                "b": self.bucket,
                "exp": self.expires_at,
                "src": [
                    {
                        "k": source.key,
                        "s": source.sha256,
                        "n": source.byte_size,
                        "p": source.page,
                    }
                    for source in self.sources
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        encoded = _b64encode(payload.encode("utf-8"))
        return f"{encoded}.{_b64encode(_mac(key, encoded))}"

    @classmethod
    def verify_grant(
        cls,
        token: str,
        *,
        keys: Iterable[bytes],
        bucket: str,
        skew_seconds: int,
        max_source_bytes: int,
        max_sources: int = MAX_MOSAIC_SOURCES,
        now: int | None = None,
    ) -> Self:
        """Return the mosaic grant the token carries, or raise :class:`GrantError`."""
        if now is None:
            now = int(time.time())
        payload = _verified_payload(token, keys)

        if payload.get("v") != MOSAIC_GRANT_VERSION:
            raise GrantError("unsupported grant version")

        if payload.get("kind") != "mosaic":
            raise GrantError("unsupported grant kind")

        expires_at = _integer(payload, "exp")
        if now > expires_at + skew_seconds:
            raise GrantError("grant has expired")

        if payload.get("b") != bucket:
            raise GrantError("grant names a bucket this tiler does not serve")

        raw_sources = payload.get("src")
        if not isinstance(raw_sources, list):
            raise GrantError("grant sources are not a list")
        raw_items = cast(list[object], raw_sources)
        if not 1 <= len(raw_items) <= max_sources:
            raise GrantError("grant source count is out of bounds")

        sources: list[GrantSource] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise GrantError("grant source is not an object")
            item = cast(dict[str, object], raw_item)
            object_key, sha256 = item.get("k"), item.get("s")
            byte_size, page = _integer(item, "n"), _integer(item, "p")
            if not isinstance(object_key, str) or not is_safe_key(object_key):
                raise GrantError("grant object key is not allowed")
            if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
                raise GrantError("grant digest is not a SHA-256")
            if byte_size < 1 or byte_size > max_source_bytes:
                raise GrantError("grant object size is out of bounds")
            if not 0 <= page <= MAX_PAGE:
                raise GrantError("grant page is out of bounds")
            sources.append(
                GrantSource(
                    key=object_key, sha256=sha256, byte_size=byte_size, page=page
                )
            )

        return cls(bucket=bucket, sources=tuple(sources), expires_at=expires_at)


def mosaic_digest(sources: Iterable[GrantSource]) -> str:
    """Stable SHA-256 digest over ordered (sha256, page) source identities."""
    canonical = json.dumps(
        [[source.sha256, source.page] for source in sources],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def is_safe_key(key: str) -> bool:
    if _KEY_PATTERN.fullmatch(key) is None:
        return False
    return all(part not in {"", ".", ".."} for part in key.split("/"))


def _integer(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    # bool is an int subclass; a JSON `true` must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise GrantError(f"grant field {name!r} is not an integer")
    return value


def _verified_payload(token: str, keys: Iterable[bytes]) -> dict[str, object]:
    encoded, separator, signature = token.partition(".")
    if separator == "" or encoded == "" or signature == "":
        raise GrantError("malformed grant")
    presented = _b64decode(signature)

    # Evaluate every key so timing does not reveal which one matched.
    verified = False
    for signing_key in keys:
        verified |= hmac.compare_digest(_mac(signing_key, encoded), presented)
    if not verified:
        raise GrantError("grant signature is invalid")

    try:
        raw = cast(object, json.loads(_b64decode(encoded)))
    except ValueError as error:
        raise GrantError("grant payload is not JSON") from error
    if not isinstance(raw, dict):
        raise GrantError("grant payload is not an object")
    return cast(dict[str, object], raw)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError) as error:
        raise GrantError("grant is not base64url") from error


def _mac(key: bytes, encoded_payload: str) -> bytes:
    return hmac.new(key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
