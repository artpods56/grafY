import json
from pathlib import Path
from types import SimpleNamespace
import sys
from uuid import UUID

import pytest

from grafy_api import cli
from grafy_persistence.system_cutover import (
    CutoverRollbackUnit,
    CutoverStoreReport,
    SystemBaselineManifest,
    SystemBaselineOperator,
    SystemBaselineRelease,
    SystemCutoverCommand,
    SystemCutoverReport,
)
from grafy_api.system_cutover_operations import (
    RollbackUnitVerificationResult,
    RollbackUnitWriteResult,
    SystemBaselineWriteResult,
    SystemCutoverFileError,
    canonical_model_json_bytes,
)


def _rollback_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    paths = (
        tmp_path / "database.backup",
        tmp_path / "release-objects.tar",
        tmp_path / "artifact-storage.tar",
        tmp_path / "migration.json",
    )
    for position, path in enumerate(paths):
        path.write_bytes(f"rollback:{position}".encode())
    return paths


def _baseline() -> SystemBaselineManifest:
    return SystemBaselineManifest(
        releases=(
            SystemBaselineRelease(
                release_id=UUID("00000000-0000-0000-0000-000000001212"),
                slug="builtin.text",
                revision=1,
                selection_generation=1,
                source_digest="1" * 64,
                lock_digest="2" * 64,
                descriptor_digest="3" * 64,
                contract_digest="4" * 64,
                capability_digest="5" * 64,
                protocol_digest="6" * 64,
                profile_digest="7" * 64,
                runtime_image_digest="8" * 64,
                runtime_archive_digest="9" * 64,
                operators=(
                    SystemBaselineOperator(
                        operator_id="text.concat",
                        operator_version=1,
                    ),
                ),
            ),
        )
    )


def _rollback_unit() -> CutoverRollbackUnit:
    return CutoverRollbackUnit(
        rollback_unit_id="rollback-cli-test",
        database_backup_sha256="a" * 64,
        release_objects_sha256="b" * 64,
        artifact_storage_sha256="c" * 64,
        migration_manifest_sha256="d" * 64,
    )


def test_cli_creates_and_verifies_typed_rollback_unit_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, releases, artifacts, migration = _rollback_files(tmp_path)
    manifest = tmp_path / "rollback-unit.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grafy",
            "system-cutover",
            "create-rollback-unit",
            "--rollback-unit-id",
            "rollback-cli-test",
            "--database-backup",
            str(database),
            "--release-objects",
            str(releases),
            "--artifact-storage",
            str(artifacts),
            "--migration-manifest",
            str(migration),
            "--output",
            str(manifest),
        ],
    )

    cli.main()

    created = RollbackUnitWriteResult.model_validate_json(capsys.readouterr().out)
    assert created.path == manifest
    assert manifest.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grafy",
            "system-cutover",
            "verify-rollback-unit",
            "--manifest",
            str(manifest),
            "--database-backup",
            str(database),
            "--release-objects",
            str(releases),
            "--artifact-storage",
            str(artifacts),
            "--migration-manifest",
            str(migration),
        ],
    )

    cli.main()

    verified = RollbackUnitVerificationResult.model_validate_json(
        capsys.readouterr().out
    )
    assert verified.verified is True
    artifacts.write_text("tampered", encoding="utf-8")
    with pytest.raises(SystemCutoverFileError, match="artifact_storage_sha256"):
        cli.main()


@pytest.mark.parametrize("command", ["audit", "apply"])
def test_cli_renders_typed_cutover_reports_and_passes_apply_token(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline_path = tmp_path / "baseline.json"
    rollback_path = tmp_path / "rollback.json"
    baseline_path.write_bytes(canonical_model_json_bytes(_baseline()))
    rollback_path.write_bytes(canonical_model_json_bytes(_rollback_unit()))
    captured: list[SystemCutoverCommand] = []

    async def execute(
        _service: object,
        cutover_command: SystemCutoverCommand,
    ) -> SystemCutoverReport:
        captured.append(cutover_command)
        return SystemCutoverReport(
            mode=cutover_command.mode,
            applied=cutover_command.mode == "apply",
            precondition_token="e" * 64,
            rollback_unit_id=cutover_command.rollback_unit.rollback_unit_id,
            stores=tuple(
                CutoverStoreReport(
                    store=store,
                    scanned_rows=1,
                    changed_rows=1,
                    pinned_nodes=1,
                    already_pinned_nodes=0,
                    excluded_module_nodes=0,
                )
                for store in (
                    "saved_graphs",
                    "saved_graph_revisions",
                    "collaborative_graph_heads",
                    "templates",
                    "graph_executions",
                )
            ),
            unknown_nodes=(),
            invalidated_invocation_cache_entries=1 if command == "apply" else 0,
            invalidated_materialized_node_outputs=1 if command == "apply" else 0,
            legacy_provenance_marked=0,
        )

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(resolved_database_url="sqlite+aiosqlite:///:memory:"),
    )
    monkeypatch.setattr(cli.SystemBaselineCutoverService, "execute", execute)
    arguments = [
        "grafy",
        "system-cutover",
        command,
        "--baseline",
        str(baseline_path),
        "--rollback-unit",
        str(rollback_path),
    ]
    if command == "apply":
        arguments.extend(["--precondition-token", "f" * 64])
    monkeypatch.setattr(sys, "argv", arguments)

    cli.main()

    rendered = json.loads(capsys.readouterr().out)
    assert rendered["mode"] == ("apply" if command == "apply" else "dry-run")
    assert rendered["stores"][0]["pinned_nodes"] == 1
    assert captured[0].expected_precondition_token == (
        "f" * 64 if command == "apply" else None
    )


def test_cli_requires_apply_token_and_exposes_optional_deployment_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grafy",
            "system-cutover",
            "apply",
            "--baseline",
            "baseline.json",
            "--rollback-unit",
            "rollback.json",
        ],
    )
    with pytest.raises(SystemExit) as missing_token:
        cli.main()
    assert missing_token.value.code == 2
    assert "--precondition-token" in capsys.readouterr().err

    monkeypatch.setattr(
        sys,
        "argv",
        ["grafy", "system-cutover", "generate-baseline", "--help"],
    )
    with pytest.raises(SystemExit) as help_exit:
        cli.main()
    assert help_exit.value.code == 0
    assert "--deployment-manifest" in capsys.readouterr().out


def test_cli_passes_static_and_exact_manifests_to_baseline_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "system-plugins.toml"
    deployment = tmp_path / "deployment.json"
    output = tmp_path / "baseline.json"
    captured: list[tuple[Path, Path, Path | None]] = []

    async def generate(
        _generator: object,
        *,
        inventory_path: Path,
        output: Path,
        deployment_manifest_path: Path | None = None,
    ) -> SystemBaselineWriteResult:
        captured.append((inventory_path, output, deployment_manifest_path))
        return SystemBaselineWriteResult(
            path=output,
            sha256="a" * 64,
            release_count=11,
        )

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(resolved_database_url="sqlite+aiosqlite:///:memory:"),
    )
    monkeypatch.setattr(cli, "generate_system_baseline_file", generate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grafy",
            "system-cutover",
            "generate-baseline",
            "--inventory",
            str(inventory),
            "--deployment-manifest",
            str(deployment),
            "--output",
            str(output),
        ],
    )

    cli.main()

    rendered = SystemBaselineWriteResult.model_validate_json(capsys.readouterr().out)
    assert rendered.release_count == 11
    assert captured == [(inventory, output, deployment)]
