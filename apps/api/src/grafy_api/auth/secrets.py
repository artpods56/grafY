"""Irreversible digests for credentials and one-time OIDC values."""

import hashlib


def digest_secret(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()
