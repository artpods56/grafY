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
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, cast

GRANT_VERSION: Final = 1

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


def sign_grant(grant: Grant, key: bytes) -> str:
    """Sign a read grant after the caller has authorized access to its source."""
    payload = json.dumps(
        {
            "v": GRANT_VERSION,
            "b": grant.bucket,
            "k": grant.key,
            "s": grant.sha256,
            "n": grant.byte_size,
            "p": grant.page,
            "exp": grant.expires_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = _b64encode(payload.encode("utf-8"))
    return f"{encoded}.{_b64encode(_mac(key, encoded))}"


def is_safe_key(key: str) -> bool:
    if _KEY_PATTERN.fullmatch(key) is None:
        return False
    return all(part not in {"", ".", ".."} for part in key.split("/"))


def verify_grant(
    token: str,
    *,
    keys: Iterable[bytes],
    bucket: str,
    now: int,
    skew_seconds: int,
    max_source_bytes: int,
) -> Grant:
    """Return the grant the token carries, or raise :class:`GrantError`.

    Checks, in order: shape, signature against any configured key (constant
    time), version, expiry, bucket, object key, digest, size and page. A
    failure never says which key or which byte was wrong.
    """
    encoded, separator, signature = token.partition(".")
    if separator == "" or encoded == "" or signature == "":
        raise GrantError("malformed grant")
    presented = _b64decode(signature)
    # Evaluate every key so timing does not reveal which one matched.
    verified = False
    for key in keys:
        verified |= hmac.compare_digest(_mac(key, encoded), presented)
    if not verified:
        raise GrantError("grant signature is invalid")

    try:
        raw = cast(object, json.loads(_b64decode(encoded)))
    except ValueError as error:
        raise GrantError("grant payload is not JSON") from error
    if not isinstance(raw, dict):
        raise GrantError("grant payload is not an object")
    payload = cast(dict[str, object], raw)

    if payload.get("v") != GRANT_VERSION:
        raise GrantError("unsupported grant version")
    expires_at = _integer(payload, "exp")
    if now > expires_at + skew_seconds:
        raise GrantError("grant has expired")
    granted_bucket = payload.get("b")
    if granted_bucket != bucket:
        raise GrantError("grant names a bucket this tiler does not serve")
    object_key = payload.get("k")
    if not isinstance(object_key, str) or not is_safe_key(object_key):
        raise GrantError("grant object key is not allowed")
    sha256 = payload.get("s")
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise GrantError("grant digest is not a SHA-256")
    byte_size = _integer(payload, "n")
    if byte_size < 1 or byte_size > max_source_bytes:
        raise GrantError("grant object size is out of bounds")
    page = _integer(payload, "p")
    if not 0 <= page <= MAX_PAGE:
        raise GrantError("grant page is out of bounds")
    return Grant(
        bucket=bucket,
        key=object_key,
        sha256=sha256,
        byte_size=byte_size,
        page=page,
        expires_at=expires_at,
    )


def _integer(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    # bool is an int subclass; a JSON `true` must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise GrantError(f"grant field {name!r} is not an integer")
    return value
