"""The one deployment key that seals every write-only credential (issue #202).

Node secrets and Agent keys are different records with different permissions, and they
must not drift into two rules about what "the encryption key" means: the same
base64-encoded 32 bytes under ``GRAFY_CREDENTIAL_ENCRYPTION_KEY``, and the same short id
derived from it and stored beside the ciphertext. That id is how a record written under
an old key admits it cannot be read by this server, instead of failing to decrypt on
first use.

The id is a truncated digest, not the key: it identifies which secret sealed a row
without giving anyone a way to test a candidate key offline against stored ciphertext.
"""

import base64
import binascii
from hashlib import sha256

from pydantic import SecretStr

CREDENTIAL_ENCRYPTION_KEY_VARIABLE = "GRAFY_CREDENTIAL_ENCRYPTION_KEY"
MAX_SEALED_CREDENTIAL_BYTES = 65_536
"""The largest credential one record may hold. Keys and tokens are short; a megabyte is
a mispasted document, and sealing it would grow a row that every read has to load."""


class CredentialKeyConfigurationError(RuntimeError):
    """This deployment cannot seal or unseal anything as configured."""


def resolve_credential_encryption_key(
    encryption_key: SecretStr | None,
) -> tuple[bytes, str]:
    """Return the active key and the id it is recorded under."""

    if encryption_key is None:
        raise CredentialKeyConfigurationError(
            f"{CREDENTIAL_ENCRYPTION_KEY_VARIABLE} is required for credential operations"
        )
    encoded = encryption_key.get_secret_value()
    try:
        key = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CredentialKeyConfigurationError(
            f"{CREDENTIAL_ENCRYPTION_KEY_VARIABLE} must be valid base64"
        ) from exc
    if len(key) != 32:
        raise CredentialKeyConfigurationError(
            f"{CREDENTIAL_ENCRYPTION_KEY_VARIABLE} must decode to exactly 32 bytes"
        )
    return key, credential_key_id(key)


def credential_key_id(key: bytes) -> str:
    return sha256(key).hexdigest()[:16]


__all__ = [
    "CREDENTIAL_ENCRYPTION_KEY_VARIABLE",
    "MAX_SEALED_CREDENTIAL_BYTES",
    "CredentialKeyConfigurationError",
    "credential_key_id",
    "resolve_credential_encryption_key",
]
