import hashlib
from pathlib import Path

import pytest

from grafy_api.cli_credentials import (
    CliCredentialError,
    credential_account,
    parse_sensitive_bearer_token,
    read_sensitive_token_file,
)


def test_sensitive_token_parser_returns_only_a_digest() -> None:
    secret = "secret-value-with-enough-entropy"
    credential = parse_sensitive_bearer_token(f"nrt_public.{secret}")

    assert credential.public_prefix == "nrt_public"
    assert credential.secret_digest == hashlib.sha256(secret.encode("utf-8")).digest()
    assert secret not in repr(credential)


def test_token_file_accepts_one_token_and_optional_trailing_newline(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "token"
    token = "nrt_public.secret-value-with-enough-entropy"
    token_file.write_text(f"{token}\n", encoding="utf-8")

    assert read_sensitive_token_file(token_file) == token

    token_file.write_text(f"{token}\n\n", encoding="utf-8")
    with pytest.raises(CliCredentialError):
        read_sensitive_token_file(token_file)


def test_keychain_account_does_not_expose_database_credentials() -> None:
    account = credential_account(
        "postgresql+asyncpg://operator:database-secret@db.example.test/grafy?ssl=true"
    )

    assert account.startswith("deployment:")
    assert "operator" not in account
    assert "database-secret" not in account
