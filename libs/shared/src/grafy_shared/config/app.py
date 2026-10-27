"""Process, workspace and database configuration for the Grafy application."""

import hashlib
import secrets
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal, Protocol

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS
from grafy_shared.config.origins import absolute_http_url

_BUILD_DIGEST_PATTERN = r"^[0-9a-f]{64}$"

# A working tree can hold anything, so a path larger than this contributes its size
# and modification time rather than its bytes. The digest still moves when the file
# changes, and reading the tree still costs a bounded amount at startup.
_MAX_HASHED_SOURCE_BYTES = 64 * 1024 * 1024


class _Digest(Protocol):
    """The one hash method used here, so `hashlib`'s private type stays private."""

    def update(self, obj: bytes, /) -> None: ...


def _git(root: Path, *arguments: str) -> bytes | None:
    """Run one git command, or return None when git or a repository is unavailable."""

    try:
        completed = subprocess.run(
            ("git", "-C", str(root), *arguments),
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout


def _digest_path(digest: _Digest, path: Path) -> None:
    """Fold one working-tree path into the digest, bounded by size rather than hope."""

    try:
        stat = path.stat()
    except OSError:
        digest.update(b"<absent>")
        return
    if stat.st_size > _MAX_HASHED_SOURCE_BYTES:
        digest.update(f"<large {stat.st_size} {stat.st_mtime_ns}>".encode())
        return
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<unreadable>")


def _working_tree_build_digest(root: Path) -> str | None:
    """Identify the source a process runs from, uncommitted edits included.

    A release image bakes `GRAFY_BUILD_DIGEST` as the SHA-256 of the source archive
    it was built from. A development process has no archive: it runs from a working
    tree that is edited in place. This derives the same kind of identity from that
    tree -- HEAD plus the content of every path that differs from it -- so a restart
    with no edit keeps the identity that materialized outputs and cached invocations
    already carry, and any edit to a tracked or newly added file moves it. Ignored
    paths stay out, which is what keeps a local database, an object store, `.env` and
    `node_modules` from posing as source.

    `None` means the tree could not be read, so the caller falls back to a per-process
    digest: an identity that invalidates everything beats one this process did not
    verify, because a stale output presented as current is the failure the digest
    exists to prevent.
    """

    toplevel = _git(root, "rev-parse", "--show-toplevel")
    if toplevel is None:
        return None
    repository = Path(toplevel.decode("utf-8", "surrogateescape").strip())
    head = _git(repository, "rev-parse", "HEAD")
    status = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--no-renames",
        "--untracked-files=all",
        "-z",
    )
    if head is None or status is None:
        return None
    digest = hashlib.sha256()
    digest.update(b"HEAD\0")
    digest.update(head)
    for entry in filter(None, status.split(b"\0")):
        recorded = entry.decode("utf-8", "surrogateescape")
        # `--porcelain=v1 -z` writes two status columns, a space, then the path.
        digest.update(recorded[:2].encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        relative = recorded[3:]
        digest.update(relative.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        _digest_path(digest, repository / relative)
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _cached_working_tree_build_digest(root: str) -> str | None:
    """Read the working-tree digest at most once per directory per process."""

    return _working_tree_build_digest(Path(root))


@lru_cache
def _ephemeral_build_digest() -> str:
    """Return this process's digest, generated once so it stays stable across reads.

    The last resort for a development process that cannot read its own source tree:
    no output survives it, which is the safe direction to be wrong in.
    """

    return secrets.token_hex(32)


class AppConfig(BaseSettings):
    """Where the process runs, what it logs, and which database it owns."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    workspace: Path = Path(".grafy-artifacts/workbench")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_renderer: Literal["console", "json"] = "console"
    environment: Literal["production", "development"] = "development"
    build_digest: str | None = Field(default=None, pattern=_BUILD_DIGEST_PATTERN)
    public_origin: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    database_url: SecretStr | None = None
    # Collaboration and shared execution assume one FastAPI process with one
    # HTTP worker. Startup acquires an exclusive lock under workspace when true.
    require_single_api_owner: bool = True

    @field_validator("public_origin")
    @classmethod
    def _validate_public_origin(cls, value: str) -> str:
        return absolute_http_url(value)

    @property
    def resolved_build_digest(self) -> str:
        if self.build_digest is not None:
            return self.build_digest
        if self.environment == "production":
            raise ValueError("GRAFY_BUILD_DIGEST is required in production")
        derived = _cached_working_tree_build_digest(str(Path.cwd()))
        return derived if derived is not None else _ephemeral_build_digest()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        database_path = (self.workspace / "grafy.sqlite3").resolve()
        return f"sqlite+aiosqlite:///{database_path}"

    @property
    def allowed_cors_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        )
