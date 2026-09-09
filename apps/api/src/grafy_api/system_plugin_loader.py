"""Explicit deployment manifest loader for exact System Plugin host code."""

from hashlib import sha256
from email.parser import BytesParser
from importlib import import_module
from importlib.metadata import Distribution, PackageNotFoundError, distribution
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from types import ModuleType
from typing import ClassVar, Literal, NamedTuple, Self
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from grafy_core.domain.plugin_releases import PluginCatalogManifest
from grafy_core.plugins import Plugin

from grafy_core.domain.plugin_host_bindings import (
    LoadedSystemPlugin,
    SystemHostPluginBinding,
)


SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST = "grafy-system-plugin-deployment@1"
_HOST_BUILD_DIGEST_DOMAIN = b"grafy.system-plugin-host-build.v1\x00"
_READ_CHUNK_SIZE = 1024 * 1024
_MAX_DISTRIBUTION_FILES = 10_000
_MAX_DISTRIBUTION_BYTES = 128 * 1024 * 1024
_INSTALLER_GENERATED_DIST_INFO_FILES = frozenset(
    {
        "INSTALLER",
        "RECORD",
        "REQUESTED",
        "direct_url.json",
        "uv_build.json",
        "uv_cache.json",
    }
)


class SystemPluginDeploymentError(RuntimeError):
    """A declared System Plugin deployment cannot be loaded exactly."""


class SystemPluginDeploymentValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class SystemPluginDeploymentEntry(SystemPluginDeploymentValue):
    """One exact release binding and the installed distribution that satisfies it."""

    binding: SystemHostPluginBinding
    distribution_name: str = Field(
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$",
        max_length=255,
    )
    loader_target: str = Field(
        pattern=(
            r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
            r":[A-Za-z_][A-Za-z0-9_]*$"
        ),
        max_length=512,
    )
    host_build_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("distribution_name")
    @classmethod
    def validate_distribution_name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("System Plugin distribution name must not contain padding")
        return value

    @field_validator("loader_target")
    @classmethod
    def validate_loader_target(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("System Plugin loader target must not contain padding")
        return value

    def model_post_init(self, context: object, /) -> None:
        del context
        if self.loader_target != self.binding.loader_target:
            raise ValueError(
                "System Plugin deployment loader target must match its exact binding"
            )
        if self.host_build_digest != self.binding.host_build_digest:
            raise ValueError(
                "System Plugin deployment build digest must match its exact binding"
            )


class SystemPluginDeploymentManifest(SystemPluginDeploymentValue):
    """Canonical deployment-owned inventory of exact host-loadable releases."""

    manifest_version: Literal["grafy-system-plugin-deployment@1"] = (
        SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST
    )
    plugins: tuple[SystemPluginDeploymentEntry, ...] = ()

    @field_validator("plugins")
    @classmethod
    def validate_and_order_plugins(
        cls,
        value: tuple[SystemPluginDeploymentEntry, ...],
    ) -> tuple[SystemPluginDeploymentEntry, ...]:
        slugs = [entry.binding.slug for entry in value]
        if len(slugs) != len(set(slugs)):
            raise ValueError("System Plugin deployment slugs must be unique")
        loader_targets = [entry.loader_target for entry in value]
        if len(loader_targets) != len(set(loader_targets)):
            raise ValueError("System Plugin deployment loader targets must be unique")
        return tuple(
            sorted(
                value,
                key=lambda entry: (
                    entry.binding.slug,
                    _canonical_distribution_name(entry.distribution_name),
                    entry.loader_target,
                ),
            )
        )

    @classmethod
    def from_json_bytes(cls, value: bytes) -> Self:
        return cls.model_validate_json(value)

    def canonical_json_bytes(self) -> bytes:
        return (self.model_dump_json() + "\n").encode("utf-8")


class LoadedSystemPluginDeployment(NamedTuple):
    plugins: tuple[Plugin, ...]
    loaded_plugins: tuple[LoadedSystemPlugin, ...]
    bindings: tuple[SystemHostPluginBinding, ...]


class _InstalledDistributionFingerprint(NamedTuple):
    digest: str
    files: frozenset[Path]


def load_system_plugin_deployment(
    manifest: SystemPluginDeploymentManifest,
) -> LoadedSystemPluginDeployment:
    """Load only manifest-declared Plugin targets after exact byte verification."""

    plugins: list[Plugin] = []
    loaded_plugins: list[LoadedSystemPlugin] = []
    bindings: list[SystemHostPluginBinding] = []
    fingerprints: dict[str, _InstalledDistributionFingerprint] = {}

    for entry in manifest.plugins:
        canonical_distribution_name = _canonical_distribution_name(
            entry.distribution_name
        )
        fingerprint = fingerprints.get(canonical_distribution_name)
        if fingerprint is None:
            fingerprint = _installed_distribution_fingerprint(
                entry.distribution_name,
                plugin_slug=entry.binding.slug,
            )
            fingerprints[canonical_distribution_name] = fingerprint
        if fingerprint.digest != entry.host_build_digest:
            raise SystemPluginDeploymentError(
                f"System Plugin {entry.binding.slug!r} distribution "
                f"{entry.distribution_name!r} build digest mismatch: expected "
                f"{entry.host_build_digest}, got {fingerprint.digest}"
            )

        module_name, attribute_name = entry.loader_target.split(":", maxsplit=1)
        try:
            module = import_module(module_name)
        except Exception as exc:
            raise SystemPluginDeploymentError(
                f"Failed to import System Plugin {entry.binding.slug!r} loader "
                f"target {entry.loader_target!r} from distribution "
                f"{entry.distribution_name!r}"
            ) from exc
        _require_hashed_loader_module(module, entry, fingerprint.files)
        try:
            loaded = getattr(module, attribute_name)
        except AttributeError as exc:
            raise SystemPluginDeploymentError(
                f"System Plugin {entry.binding.slug!r} loader target "
                f"{entry.loader_target!r} does not exist in distribution "
                f"{entry.distribution_name!r}"
            ) from exc
        if not isinstance(loaded, Plugin):
            raise SystemPluginDeploymentError(
                f"System Plugin {entry.binding.slug!r} loader target "
                f"{entry.loader_target!r} returned {type(loaded).__name__}, "
                "expected Plugin"
            )
        if loaded.slug != entry.binding.slug:
            raise SystemPluginDeploymentError(
                f"System Plugin loader target {entry.loader_target!r} declared "
                f"slug {loaded.slug!r}, expected {entry.binding.slug!r}"
            )
        try:
            loaded_catalog = PluginCatalogManifest.from_plugin(loaded)
        except Exception as exc:
            raise SystemPluginDeploymentError(
                f"Failed to inspect System Plugin {entry.binding.slug!r} loaded "
                f"from {entry.loader_target!r}"
            ) from exc
        if loaded_catalog != entry.binding.catalog:
            raise SystemPluginDeploymentError(
                f"System Plugin {entry.binding.slug!r} loaded catalog does not "
                "match its exact release binding"
            )

        plugins.append(loaded)
        loaded_plugins.append(
            LoadedSystemPlugin(
                slug=entry.binding.slug,
                loader_target=entry.loader_target,
                host_build_digest=fingerprint.digest,
            )
        )
        bindings.append(entry.binding)

    return LoadedSystemPluginDeployment(
        plugins=tuple(plugins),
        loaded_plugins=tuple(loaded_plugins),
        bindings=tuple(bindings),
    )


def load_system_plugin_deployment_file(
    path: Path,
) -> LoadedSystemPluginDeployment:
    """Read, validate, and load one deployment manifest."""

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SystemPluginDeploymentError(
            f"Failed to read System Plugin deployment manifest {path}"
        ) from exc
    try:
        manifest = SystemPluginDeploymentManifest.from_json_bytes(payload)
    except ValidationError as exc:
        raise SystemPluginDeploymentError(
            f"Invalid System Plugin deployment manifest {path}"
        ) from exc
    return load_system_plugin_deployment(manifest)


def installed_distribution_build_digest(distribution_name: str) -> str:
    """Return the canonical digest of regular files in one installed distribution."""

    return _installed_distribution_fingerprint(
        distribution_name,
        plugin_slug=distribution_name,
    ).digest


def wheel_distribution_build_digest(
    wheel: Path,
    distribution_name: str,
) -> str:
    """Fingerprint source-owned wheel files using the installed-build domain."""

    try:
        with ZipFile(wheel) as archive:
            infos = archive.infolist()
            files: list[tuple[str, bytes]] = []
            seen_paths: set[str] = set()
            total_bytes = 0
            metadata_documents: list[bytes] = []
            for info in infos:
                relative_path = info.filename
                _require_safe_distribution_path(
                    relative_path,
                    distribution_name=distribution_name,
                    plugin_slug=distribution_name,
                )
                if relative_path in seen_paths:
                    raise SystemPluginDeploymentError(
                        f"System Plugin distribution {distribution_name!r} wheel "
                        f"declares duplicate file path {relative_path!r}"
                    )
                seen_paths.add(relative_path)
                if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                    raise SystemPluginDeploymentError(
                        f"System Plugin distribution {distribution_name!r} wheel "
                        f"file {relative_path!r} is not regular"
                    )
                if info.flag_bits & 0x1:
                    raise SystemPluginDeploymentError(
                        f"System Plugin distribution {distribution_name!r} wheel "
                        f"file {relative_path!r} is encrypted"
                    )
                total_bytes += info.file_size
                if (
                    len(seen_paths) > _MAX_DISTRIBUTION_FILES
                    or total_bytes > _MAX_DISTRIBUTION_BYTES
                ):
                    raise SystemPluginDeploymentError(
                        f"System Plugin distribution {distribution_name!r} wheel "
                        "exceeds canonical fingerprint limits"
                    )
                content = archive.read(info)
                if relative_path.endswith(".dist-info/METADATA"):
                    metadata_documents.append(content)
                if _is_installer_generated_distribution_path(relative_path):
                    continue
                files.append((relative_path, content))
    except (BadZipFile, OSError) as exc:
        raise SystemPluginDeploymentError(
            f"Failed to inspect System Plugin distribution "
            f"{distribution_name!r} wheel {wheel}"
        ) from exc
    if len(metadata_documents) != 1:
        raise SystemPluginDeploymentError(
            f"System Plugin distribution {distribution_name!r} wheel must contain "
            "one METADATA document"
        )
    actual_name = BytesParser().parsebytes(metadata_documents[0]).get("Name")
    if actual_name is None or _canonical_distribution_name(
        actual_name
    ) != _canonical_distribution_name(distribution_name):
        raise SystemPluginDeploymentError(
            f"System Plugin distribution {distribution_name!r} wheel metadata "
            f"declares {actual_name!r}"
        )
    return _distribution_files_digest(distribution_name, files)


def write_system_plugin_deployment_manifest(
    path: Path,
    manifest: SystemPluginDeploymentManifest,
) -> Path:
    """Atomically write one canonical deployment manifest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(manifest.canonical_json_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        raise SystemPluginDeploymentError(
            f"Failed to write System Plugin deployment manifest {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return path


def _installed_distribution_fingerprint(
    distribution_name: str,
    *,
    plugin_slug: str,
) -> _InstalledDistributionFingerprint:
    try:
        installed = distribution(distribution_name)
    except PackageNotFoundError as exc:
        raise SystemPluginDeploymentError(
            f"System Plugin {plugin_slug!r} distribution "
            f"{distribution_name!r} is not installed"
        ) from exc
    except Exception as exc:
        raise SystemPluginDeploymentError(
            f"Failed to inspect System Plugin {plugin_slug!r} distribution "
            f"{distribution_name!r}"
        ) from exc
    actual_name = installed.metadata.get("Name")
    if actual_name is None or _canonical_distribution_name(
        actual_name
    ) != _canonical_distribution_name(distribution_name):
        raise SystemPluginDeploymentError(
            f"System Plugin {plugin_slug!r} requested distribution "
            f"{distribution_name!r}, but importlib resolved {actual_name!r}"
        )
    return _fingerprint_distribution_files(
        installed,
        distribution_name=distribution_name,
        plugin_slug=plugin_slug,
    )


def _fingerprint_distribution_files(
    installed: Distribution,
    *,
    distribution_name: str,
    plugin_slug: str,
) -> _InstalledDistributionFingerprint:
    files = installed.files
    if not files:
        raise SystemPluginDeploymentError(
            f"System Plugin {plugin_slug!r} distribution "
            f"{distribution_name!r} has no installed file inventory"
        )
    try:
        root = Path(str(installed.locate_file(""))).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SystemPluginDeploymentError(
            f"System Plugin {plugin_slug!r} distribution "
            f"{distribution_name!r} has an inaccessible installation root"
        ) from exc
    if not root.is_dir():
        raise SystemPluginDeploymentError(
            f"System Plugin {plugin_slug!r} distribution "
            f"{distribution_name!r} installation root is not a directory"
        )

    located_files: list[tuple[str, Path]] = []
    seen_paths: set[str] = set()
    for declared_file in files:
        relative_path = str(declared_file)
        _require_safe_distribution_path(
            relative_path,
            distribution_name=distribution_name,
            plugin_slug=plugin_slug,
        )
        if relative_path in seen_paths:
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} declares duplicate file path "
                f"{relative_path!r}"
            )
        seen_paths.add(relative_path)
        if _is_installer_generated_distribution_path(relative_path):
            continue
        normalized = PurePosixPath(relative_path)
        candidate = Path(str(installed.locate_file(declared_file)))
        lexical_cursor = root
        for segment in normalized.parts:
            lexical_cursor /= segment
            if lexical_cursor.is_symlink():
                raise SystemPluginDeploymentError(
                    f"System Plugin {plugin_slug!r} distribution "
                    f"{distribution_name!r} file {relative_path!r} traverses a "
                    "symbolic link"
                )
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} file {relative_path!r} is missing"
            ) from exc
        if not resolved.is_relative_to(root):
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} file {relative_path!r} escapes its "
                "installation root"
            )
        try:
            mode = resolved.lstat().st_mode
        except OSError as exc:
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} file {relative_path!r} cannot be inspected"
            ) from exc
        if not stat.S_ISREG(mode):
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} file {relative_path!r} is not regular"
            )
        located_files.append((relative_path, resolved))

    contents: list[tuple[str, bytes]] = []
    resolved_files: set[Path] = set()
    total_bytes = 0
    for relative_path, resolved in sorted(located_files):
        try:
            descriptor = os.open(
                resolved,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} file {relative_path!r} cannot be read"
            ) from exc
        with os.fdopen(descriptor, "rb") as stream:
            file_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_stat.st_mode):
                raise SystemPluginDeploymentError(
                    f"System Plugin {plugin_slug!r} distribution "
                    f"{distribution_name!r} file {relative_path!r} is not regular"
                )
            content_chunks: list[bytes] = []
            bytes_read = 0
            while content := stream.read(_READ_CHUNK_SIZE):
                content_chunks.append(content)
                bytes_read += len(content)
            if bytes_read != file_stat.st_size:
                raise SystemPluginDeploymentError(
                    f"System Plugin {plugin_slug!r} distribution "
                    f"{distribution_name!r} file {relative_path!r} changed while "
                    "being read"
                )
        contents.append((relative_path, b"".join(content_chunks)))
        total_bytes += bytes_read
        if (
            len(contents) > _MAX_DISTRIBUTION_FILES
            or total_bytes > _MAX_DISTRIBUTION_BYTES
        ):
            raise SystemPluginDeploymentError(
                f"System Plugin {plugin_slug!r} distribution "
                f"{distribution_name!r} exceeds canonical fingerprint limits"
            )
        resolved_files.add(resolved)
    return _InstalledDistributionFingerprint(
        digest=_distribution_files_digest(distribution_name, contents),
        files=frozenset(resolved_files),
    )


def _require_safe_distribution_path(
    relative_path: str,
    *,
    distribution_name: str,
    plugin_slug: str,
) -> None:
    segments = relative_path.split("/")
    normalized = PurePosixPath(relative_path)
    if (
        relative_path == ""
        or "\\" in relative_path
        or normalized.is_absolute()
        or any(segment in {"", ".", ".."} for segment in segments)
        or normalized.as_posix() != relative_path
    ):
        raise SystemPluginDeploymentError(
            f"System Plugin {plugin_slug!r} distribution "
            f"{distribution_name!r} declares unsafe file path {relative_path!r}"
        )


def _is_installer_generated_distribution_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if "__pycache__" in path.parts or path.suffix == ".pyc":
        return True
    if len(path.parts) < 2 or not path.parts[-2].endswith(".dist-info"):
        return False
    return path.name in _INSTALLER_GENERATED_DIST_INFO_FILES


def _distribution_files_digest(
    distribution_name: str,
    files: list[tuple[str, bytes]],
) -> str:
    digest = sha256()
    digest.update(_HOST_BUILD_DIGEST_DOMAIN)
    canonical_name = _canonical_distribution_name(distribution_name).encode("utf-8")
    digest.update(len(canonical_name).to_bytes(8, "big"))
    digest.update(canonical_name)
    for relative_path, content in sorted(files):
        path_bytes = relative_path.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _require_hashed_loader_module(
    module: ModuleType,
    entry: SystemPluginDeploymentEntry,
    hashed_files: frozenset[Path],
) -> None:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str) or module_file == "":
        raise SystemPluginDeploymentError(
            f"System Plugin {entry.binding.slug!r} loader module "
            f"{entry.loader_target!r} has no regular distribution file"
        )
    try:
        resolved = Path(module_file).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SystemPluginDeploymentError(
            f"System Plugin {entry.binding.slug!r} loader module "
            f"{entry.loader_target!r} file is missing"
        ) from exc
    if resolved not in hashed_files:
        raise SystemPluginDeploymentError(
            f"System Plugin {entry.binding.slug!r} loader module "
            f"{entry.loader_target!r} is not owned by declared distribution "
            f"{entry.distribution_name!r}"
        )


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


__all__ = [
    "LoadedSystemPluginDeployment",
    "SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST",
    "SystemPluginDeploymentEntry",
    "SystemPluginDeploymentError",
    "SystemPluginDeploymentManifest",
    "installed_distribution_build_digest",
    "load_system_plugin_deployment",
    "load_system_plugin_deployment_file",
    "write_system_plugin_deployment_manifest",
    "wheel_distribution_build_digest",
]
