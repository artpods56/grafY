"""Sensitive credential input and storage for the Grafy CLI."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re

import keyring
from keyring.errors import KeyringError
from sqlalchemy.engine import make_url


KEYRING_SERVICE = "grafy-cli"
TOKEN_FILE_ENVIRONMENT_VARIABLE = "GRAFY_TOKEN_FILE"
MAX_TOKEN_FILE_BYTES = 4 * 1024


class CliCredentialError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialDigest:
    public_prefix: str
    secret_digest: bytes


def credential_account(database_url: str) -> str:
    url = make_url(database_url)
    database_identity = "|".join(
        (
            url.drivername,
            url.host or "",
            str(url.port or ""),
            url.database or "",
        )
    )
    digest = hashlib.sha256(database_identity.encode("utf-8")).hexdigest()
    return f"deployment:{digest}"


def parse_sensitive_bearer_token(value: str) -> CredentialDigest:
    public_prefix, separator, secret = value.partition(".")
    if (
        not separator
        or not re.fullmatch(r"nrt_[A-Za-z0-9_-]{1,27}", public_prefix)
        or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", secret)
    ):
        raise CliCredentialError("Credential has an invalid format")
    return CredentialDigest(
        public_prefix=public_prefix,
        secret_digest=hashlib.sha256(secret.encode("utf-8")).digest(),
    )


def read_sensitive_token_file(path: Path) -> str:
    try:
        payload = path.expanduser().read_bytes()
    except OSError as exc:
        raise CliCredentialError(f"Cannot read credential file {path}: {exc}") from exc
    if len(payload) > MAX_TOKEN_FILE_BYTES:
        raise CliCredentialError("Credential file exceeds 4 KiB")
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CliCredentialError("Credential file must contain UTF-8 text") from exc
    if value.endswith("\n"):
        value = value[:-1]
    if value == "" or any(character.isspace() for character in value):
        raise CliCredentialError(
            "Credential file must contain one token and an optional trailing newline"
        )
    return value


def load_sensitive_cli_token(database_url: str) -> str:
    token_file = os.environ.get(TOKEN_FILE_ENVIRONMENT_VARIABLE)
    if token_file is not None:
        if token_file.strip() == "":
            raise CliCredentialError(
                f"{TOKEN_FILE_ENVIRONMENT_VARIABLE} must not be blank"
            )
        return read_sensitive_token_file(Path(token_file))
    try:
        value = keyring.get_password(KEYRING_SERVICE, credential_account(database_url))
    except KeyringError as exc:
        raise CliCredentialError(
            "The OS keychain is unavailable; set GRAFY_TOKEN_FILE to a protected "
            "credential file for non-interactive use"
        ) from exc
    if value is None:
        raise CliCredentialError(
            "No Grafy credential is stored; run 'grafy auth login' or set "
            "GRAFY_TOKEN_FILE"
        )
    return value


def store_sensitive_cli_token(database_url: str, value: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, credential_account(database_url), value)
    except KeyringError as exc:
        raise CliCredentialError(
            "The OS keychain is unavailable; use GRAFY_TOKEN_FILE for "
            "non-interactive credentials"
        ) from exc


def delete_sensitive_cli_token(database_url: str) -> bool:
    account = credential_account(database_url)
    try:
        if keyring.get_password(KEYRING_SERVICE, account) is None:
            return False
        keyring.delete_password(KEYRING_SERVICE, account)
    except KeyringError as exc:
        raise CliCredentialError("The OS keychain is unavailable") from exc
    return True


__all__ = [
    "CliCredentialError",
    "CredentialDigest",
    "credential_account",
    "delete_sensitive_cli_token",
    "load_sensitive_cli_token",
    "parse_sensitive_bearer_token",
    "read_sensitive_token_file",
    "store_sensitive_cli_token",
]
