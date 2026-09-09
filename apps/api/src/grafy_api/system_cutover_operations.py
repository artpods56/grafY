"""Operator file operations for System baseline and rollback manifests."""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from grafy_persistence.system_cutover import (
    CutoverRollbackUnit,
    SystemBaselineManifest,
)
from grafy_api.system_plugin_inventory import (
    load_system_plugin_inventory,
)
from grafy_persistence.system_baseline import (
    SystemBaselineManifestGenerator,
)
from grafy_core.domain.system_plugin_inventory import (
    SystemPluginInventory,
)
from grafy_api.plugins.compatibility.loader import SystemPluginDeploymentManifest


class SystemCutoverFileError(RuntimeError):
    """A cutover manifest or explicitly named rollback file is invalid."""


class _OperationResult(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class SystemBaselineWriteResult(_OperationResult):
    kind: Literal["system-baseline"] = "system-baseline"
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_count: int = Field(ge=1)


class RollbackUnitWriteResult(_OperationResult):
    kind: Literal["rollback-unit"] = "rollback-unit"
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_unit_id: str


class RollbackUnitVerificationResult(_OperationResult):
    kind: Literal["rollback-unit-verification"] = "rollback-unit-verification"
    verified: Literal[True] = True
    manifest_path: Path
    rollback_unit: CutoverRollbackUnit


def canonical_model_json_bytes(model: BaseModel) -> bytes:
    """Serialize a typed manifest deterministically for checksums and review."""

    document = model.model_dump(mode="json")
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_manifest(path: Path, model: BaseModel) -> str:
    payload = canonical_model_json_bytes(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.chmod(temporary.name, 0o600)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise SystemCutoverFileError(f"Cannot write cutover manifest {path}") from exc
    return sha256(payload).hexdigest()


def _read_model[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        payload = path.read_bytes()
        return model_type.model_validate_json(payload)
    except (OSError, ValidationError) as exc:
        raise SystemCutoverFileError(
            f"Cannot load {model_type.__name__} from {path}: {exc}"
        ) from exc


def load_system_baseline_manifest(path: Path) -> SystemBaselineManifest:
    return _read_model(path, SystemBaselineManifest)


def load_rollback_unit(path: Path) -> CutoverRollbackUnit:
    return _read_model(path, CutoverRollbackUnit)


def _file_sha256(path: Path, *, label: str) -> str:
    digest = sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SystemCutoverFileError(f"Cannot checksum {label} file {path}") from exc
    return digest.hexdigest()


def create_rollback_unit_manifest(
    *,
    rollback_unit_id: str,
    database_backup: Path,
    release_objects: Path,
    artifact_storage: Path,
    migration_manifest: Path,
    output: Path,
) -> RollbackUnitWriteResult:
    rollback_unit = CutoverRollbackUnit(
        rollback_unit_id=rollback_unit_id,
        database_backup_sha256=_file_sha256(
            database_backup,
            label="database backup",
        ),
        release_objects_sha256=_file_sha256(
            release_objects,
            label="release objects",
        ),
        artifact_storage_sha256=_file_sha256(
            artifact_storage,
            label="artifact storage",
        ),
        migration_manifest_sha256=_file_sha256(
            migration_manifest,
            label="migration manifest",
        ),
    )
    manifest_sha256 = _write_manifest(output, rollback_unit)
    return RollbackUnitWriteResult(
        path=output,
        sha256=manifest_sha256,
        rollback_unit_id=rollback_unit.rollback_unit_id,
    )


def verify_rollback_unit_manifest(
    *,
    manifest: Path,
    database_backup: Path,
    release_objects: Path,
    artifact_storage: Path,
    migration_manifest: Path,
) -> RollbackUnitVerificationResult:
    expected = load_rollback_unit(manifest)
    actual = CutoverRollbackUnit(
        rollback_unit_id=expected.rollback_unit_id,
        database_backup_sha256=_file_sha256(
            database_backup,
            label="database backup",
        ),
        release_objects_sha256=_file_sha256(
            release_objects,
            label="release objects",
        ),
        artifact_storage_sha256=_file_sha256(
            artifact_storage,
            label="artifact storage",
        ),
        migration_manifest_sha256=_file_sha256(
            migration_manifest,
            label="migration manifest",
        ),
    )
    if actual != expected:
        mismatches = [
            field
            for field in (
                "database_backup_sha256",
                "release_objects_sha256",
                "artifact_storage_sha256",
                "migration_manifest_sha256",
            )
            if getattr(actual, field) != getattr(expected, field)
        ]
        raise SystemCutoverFileError(
            "Rollback unit checksum mismatch: " + ", ".join(mismatches)
        )
    return RollbackUnitVerificationResult(
        manifest_path=manifest,
        rollback_unit=expected,
    )


async def generate_system_baseline_file(
    generator: SystemBaselineManifestGenerator,
    *,
    inventory_path: Path,
    output: Path,
    deployment_manifest_path: Path | None = None,
) -> SystemBaselineWriteResult:
    inventory = load_system_plugin_inventory(inventory_path)
    host_bindings = None
    if deployment_manifest_path is not None:
        deployment = _read_model(
            deployment_manifest_path,
            SystemPluginDeploymentManifest,
        )
        _verify_deployment_inventory(inventory, deployment)
        host_bindings = tuple(entry.binding for entry in deployment.plugins)
    baseline = await generator.generate(inventory, host_bindings=host_bindings)
    baseline_sha256 = _write_manifest(output, baseline)
    return SystemBaselineWriteResult(
        path=output,
        sha256=baseline_sha256,
        release_count=len(baseline.releases),
    )


def _verify_deployment_inventory(
    inventory: SystemPluginInventory,
    deployment: SystemPluginDeploymentManifest,
) -> None:
    inventory_by_slug = {entry.slug: entry for entry in inventory.plugins}
    for deployed in deployment.plugins:
        static = inventory_by_slug.get(deployed.binding.slug)
        if static is None:
            raise SystemCutoverFileError(
                f"Deployment binding {deployed.binding.slug!r} is not in the "
                "static System inventory"
            )
        if deployed.distribution_name != static.distribution_name:
            raise SystemCutoverFileError(
                f"Deployment binding {deployed.binding.slug!r} distribution does "
                "not match the static System inventory"
            )
        if deployed.loader_target != static.loader_target:
            raise SystemCutoverFileError(
                f"Deployment binding {deployed.binding.slug!r} loader target does "
                "not match the static System inventory"
            )


__all__ = [
    "RollbackUnitVerificationResult",
    "RollbackUnitWriteResult",
    "SystemBaselineWriteResult",
    "SystemCutoverFileError",
    "canonical_model_json_bytes",
    "create_rollback_unit_manifest",
    "generate_system_baseline_file",
    "load_rollback_unit",
    "load_system_baseline_manifest",
    "verify_rollback_unit_manifest",
]
