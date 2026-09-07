from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import gzip
import shutil
import tarfile

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_api.plugins.publication.source import (
    PluginDirectoryPublisher,
    PluginPublishingError,
    constrained_environment,
    build_deterministic_archive,
    project_loader_target,
    scan_source_tree,
    unpack_source_snapshot,
    validate_relative_source_name,
)
from grafy_core.domain.plugin_releases import (
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginRelease,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PLUGIN = REPOSITORY_ROOT / "examples" / "plugin-notes"


def test_project_can_own_a_non_generic_loader_target() -> None:
    assert project_loader_target(REPOSITORY_ROOT / "plugins" / "llm") == (
        "grafy_plugin_llm.plugin:LLM"
    )


def _copy_example_plugin(destination_root: Path) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    project = destination_root / "plugin-notes"
    project.mkdir()
    for entry in ("pyproject.toml", "uv.lock", "wheels", "src", "tests"):
        source = EXAMPLE_PLUGIN / entry
        target = project / entry
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return project


def _minimal_catalog(
    required_capabilities: tuple[PluginRuntimeCapability, ...] = (),
) -> PluginCatalogManifest:
    return PluginCatalogManifest(
        slug="notes",
        title="Notes",
        nodes=(
            PluginNodeContract(
                operator_id="notes.echo",
                operator_version=1,
                title="Echo",
                description="Echo text",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
                required_capabilities=required_capabilities,
            ),
        ),
    )


def test_plugin_directory_is_tested_inspected_and_frozen(tmp_path: Path) -> None:
    verified = PluginDirectoryPublisher(
        (REPOSITORY_ROOT / "examples",), runtime_profile="python-uv"
    ).verify(EXAMPLE_PLUGIN)

    assert verified.catalog.slug == "notes"
    assert {node.operator_id for node in verified.catalog.nodes} == {
        "notes.table.summarize",
        "notes.summary.render",
    }
    assert verified.runtime_profile == "python-uv"
    assert len(verified.lock_digest) == 64
    archive_path = tmp_path / "source.tar.gz"
    archive_path.write_bytes(verified.source_archive)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        names = set(archive.getnames())
    assert {
        "pyproject.toml",
        "uv.lock",
        "src/grafy_plugin/__init__.py",
        "src/grafy_plugin/nodes.py",
        "tests/test_nodes.py",
    } <= names
    assert all(not name.startswith(".venv/") for name in names)
    assert not any(name.endswith(".json") for name in names)


def test_host_secrets_cannot_reach_the_verification_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRAFY_PLUGIN_SENTINEL_SECRET", "s3cret-value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://leaked")

    verified = PluginDirectoryPublisher(
        (REPOSITORY_ROOT / "examples",), runtime_profile="python-uv"
    ).verify(EXAMPLE_PLUGIN)

    assert verified.catalog.slug == "notes"
    environment = constrained_environment(
        Path("/snapshot/.venv/bin/python"), Path("/staging/home")
    )
    assert "GRAFY_PLUGIN_SENTINEL_SECRET" not in environment.values()
    assert "DATABASE_URL" not in environment


def test_tests_mutating_the_working_copy_cannot_change_the_freeze(
    tmp_path: Path,
) -> None:
    project = _copy_example_plugin(tmp_path)
    mutation_test = project / "tests" / "test_mutate_working_copy.py"
    mutation_test.write_text(
        "from pathlib import Path\n"
        "\n"
        "\n"
        f"WORKING_COPY = Path({str(project)!r})\n"
        "\n"
        "\n"
        "def test_mutate_everything() -> None:\n"
        "    nodes = WORKING_COPY / 'src' / 'grafy_plugin' / 'nodes.py'\n"
        "    nodes.write_text('# mutated during tests\\n', encoding='utf-8')\n"
        "    (WORKING_COPY / 'EXTRA.txt').write_text('mutated', encoding='utf-8')\n",
        encoding="utf-8",
    )
    expected_archive = build_deterministic_archive(scan_source_tree(project))

    verified = PluginDirectoryPublisher(
        (tmp_path,), runtime_profile="python-uv"
    ).verify(project)

    assert verified.source_archive == expected_archive
    assert (project / "EXTRA.txt").exists()
    snapshot = tmp_path / "unpacked"
    snapshot.mkdir()
    unpack_source_snapshot(verified.source_archive, snapshot)
    stored_nodes = (snapshot / "src" / "grafy_plugin" / "nodes.py").read_text(
        encoding="utf-8"
    )
    assert "# mutated during tests" not in stored_nodes


def test_source_digest_is_stable_under_enumeration_reorder() -> None:
    entries = scan_source_tree(EXAMPLE_PLUGIN)

    forward_digest = sha256(build_deterministic_archive(entries)).hexdigest()
    backward_digest = sha256(
        build_deterministic_archive(list(reversed(entries)))
    ).hexdigest()

    assert forward_digest == backward_digest


def test_generated_release_metadata_does_not_change_the_source_digest() -> None:
    source_archive = build_deterministic_archive(scan_source_tree(EXAMPLE_PLUGIN))
    source_digest = sha256(source_archive).hexdigest()

    releases = [
        PluginRelease(
            slug="notes",
            revision=revision,
            catalog=_minimal_catalog(capabilities),
            contract_digest=plugin_contract_digest(_minimal_catalog(capabilities)),
            capabilities=PluginCapabilityManifest(capabilities=capabilities),
            capability_digest=PluginCapabilityManifest(
                capabilities=capabilities
            ).digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest(runtime_profile),
            source_object_key=f"plugin-releases/notes/{revision}.tar.gz",
            source_digest=source_digest,
            lock_digest="2" * 64,
            runtime_profile=runtime_profile,
            loader_target="grafy_plugin:PLUGIN",
            published_at=datetime.now(UTC),
        )
        for revision, capabilities, runtime_profile in (
            (1, (), "python-uv"),
            (2, (PluginRuntimeCapability.NETWORK_EGRESS,), "python-uv-gdal"),
        )
    ]

    assert {release.source_digest for release in releases} == {source_digest}


@pytest.mark.parametrize(
    "candidate",
    ["../escaped.py", "/absolute.py", "a/../b.py", "back\\slash.py"],
)
def test_escaping_source_names_are_rejected(candidate: str) -> None:
    with pytest.raises(PluginPublishingError, match="escaping source path"):
        validate_relative_source_name(candidate)


def test_symlink_in_project_is_rejected_with_contextual_information(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("secret = True\n", encoding="utf-8")
    project = _copy_example_plugin(tmp_path / "roots")
    link = project / "src" / "grafy_plugin" / "link.py"
    link.symlink_to(outside)

    with pytest.raises(PluginPublishingError) as excinfo:
        scan_source_tree(project)

    message = str(excinfo.value)
    assert "src/grafy_plugin/link.py" in message
    assert str(outside) in message


def test_path_dependencies_outside_the_snapshot_are_rejected(tmp_path: Path) -> None:
    project = _copy_example_plugin(tmp_path / "roots")
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'grafy-core = { path = "wheels/grafy_core-0.1.0-py3-none-any.whl" }',
            'grafy-core = { path = "wheels/grafy_core-0.1.0-py3-none-any.whl" }\n'
            'escaping = { path = "../../libs/core" }',
        ),
        encoding="utf-8",
    )

    with pytest.raises(PluginPublishingError) as excinfo:
        PluginDirectoryPublisher(
            (tmp_path / "roots",), runtime_profile="python-uv"
        ).verify(project)

    message = str(excinfo.value)
    assert "'escaping'" in message
    assert "../../libs/core" in message


def test_project_must_be_below_an_allowed_root(tmp_path: Path) -> None:
    with pytest.raises(PluginPublishingError, match="outside configured roots"):
        PluginDirectoryPublisher((tmp_path,), runtime_profile="python-uv").verify(
            EXAMPLE_PLUGIN
        )


def test_inspected_slug_must_match_the_publish_target() -> None:
    with pytest.raises(PluginPublishingError) as excinfo:
        PluginDirectoryPublisher(
            (REPOSITORY_ROOT / "examples",), runtime_profile="python-uv"
        ).verify(
            EXAMPLE_PLUGIN,
            expected_slug="other",
        )

    message = str(excinfo.value)
    assert "'other'" in message
    assert "'notes'" in message


def test_unpacked_snapshot_rejects_unsupported_archive_entries(tmp_path: Path) -> None:
    buffer = BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            info = tarfile.TarInfo("../escape.py")
            info.size = 0
            archive.addfile(info)
    destination = tmp_path / "unpack"
    destination.mkdir()

    with pytest.raises(PluginPublishingError, match="escape.py"):
        unpack_source_snapshot(buffer.getvalue(), destination)
