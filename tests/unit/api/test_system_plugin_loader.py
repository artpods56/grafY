import stat
from email.message import Message
from importlib.metadata import Distribution, PackageNotFoundError, PackagePath
from pathlib import Path
from types import ModuleType
from typing import cast
from unittest.mock import Mock
from uuid import UUID, uuid4
from zipfile import ZipFile, ZipInfo

from pydantic import ValidationError
import pytest

from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    plugin_contract_digest,
)
from grafy_core.plugins import Plugin
from grafy_workbench.arithmetic import ARITHMETIC
from grafy_workbench.text import TEXT

from grafy_api.plugins.compatibility import loader as system_plugin_loader
from grafy_core.domain.plugin_host_bindings import (
    LoadedSystemPlugin,
    SystemHostPluginBinding,
)
from grafy_api.plugins.compatibility.loader import (
    SystemPluginDeploymentEntry,
    SystemPluginDeploymentError,
    SystemPluginDeploymentManifest,
    installed_distribution_build_digest,
    load_system_plugin_deployment,
    wheel_distribution_build_digest,
    load_system_plugin_deployment_file,
    write_system_plugin_deployment_manifest,
)


_DISTRIBUTION_NAME = "grafy-plugin-test-system"
_LOADER_TARGET = "grafy_test_system_plugin:PLUGIN"
_RELEASE_ID = UUID("00000000-0000-0000-0000-000000000901")


class _InstalledDistribution:
    def __init__(
        self,
        root: Path,
        files: tuple[str, ...],
        *,
        name: str = _DISTRIBUTION_NAME,
    ) -> None:
        self._root = root
        self._files = tuple(PackagePath(path) for path in files)
        self._metadata = Message()
        self._metadata["Name"] = name

    @property
    def files(self) -> tuple[PackagePath, ...]:
        return self._files

    @property
    def metadata(self) -> Message:
        return self._metadata

    def locate_file(self, path: object) -> Path:
        return self._root / str(path)


def _installed_tree(tmp_path: Path) -> tuple[_InstalledDistribution, Path]:
    plugin_file = tmp_path / "grafy_test_system_plugin.py"
    plugin_file.write_text("# exact installed plugin bytes\n", encoding="utf-8")
    metadata_file = tmp_path / "grafy_plugin_test_system-1.0.dist-info" / "METADATA"
    metadata_file.parent.mkdir()
    metadata_file.write_text(
        "Metadata-Version: 2.4\nName: grafy-plugin-test-system\nVersion: 1.0\n",
        encoding="utf-8",
    )
    return (
        _InstalledDistribution(
            tmp_path,
            (
                "grafy_plugin_test_system-1.0.dist-info/METADATA",
                "grafy_test_system_plugin.py",
            ),
        ),
        plugin_file,
    )


def _binding(
    host_build_digest: str,
    *,
    catalog: PluginCatalogManifest | None = None,
    loader_target: str = _LOADER_TARGET,
) -> SystemHostPluginBinding:
    effective_catalog = catalog or PluginCatalogManifest.from_plugin(TEXT)
    return SystemHostPluginBinding(
        release_id=_RELEASE_ID,
        slug=effective_catalog.slug,
        revision=3,
        selection_generation=2,
        descriptor_digest="a" * 64,
        contract_digest=plugin_contract_digest(effective_catalog),
        source_digest="b" * 64,
        runtime_archive_digest="c" * 64,
        loader_target=loader_target,
        host_build_digest=host_build_digest,
        catalog=effective_catalog,
    )


def _manifest(binding: SystemHostPluginBinding) -> SystemPluginDeploymentManifest:
    return SystemPluginDeploymentManifest(
        plugins=(
            SystemPluginDeploymentEntry(
                binding=binding,
                distribution_name=_DISTRIBUTION_NAME,
                loader_target=binding.loader_target,
                host_build_digest=binding.host_build_digest,
            ),
        )
    )


def _exact_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    SystemPluginDeploymentManifest,
    _InstalledDistribution,
    ModuleType,
    Mock,
]:
    installed, plugin_file = _installed_tree(tmp_path)
    distribution_lookup = Mock(return_value=cast(Distribution, installed))
    monkeypatch.setattr(system_plugin_loader, "distribution", distribution_lookup)
    host_build_digest = installed_distribution_build_digest(_DISTRIBUTION_NAME)
    distribution_lookup.reset_mock()
    module = ModuleType("grafy_test_system_plugin")
    module.__file__ = str(plugin_file)
    module.PLUGIN = TEXT  # type: ignore[attr-defined]
    importer = Mock(return_value=module)
    monkeypatch.setattr(system_plugin_loader, "import_module", importer)
    return _manifest(_binding(host_build_digest)), installed, module, importer


def test_loader_returns_exact_plugins_manifests_and_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, _, importer = _exact_manifest(tmp_path, monkeypatch)

    loaded = load_system_plugin_deployment(manifest)

    assert loaded.plugins == (TEXT,)
    assert loaded.loaded_plugins == (
        LoadedSystemPlugin(
            slug="text",
            loader_target=_LOADER_TARGET,
            host_build_digest=manifest.plugins[0].host_build_digest,
        ),
    )
    assert loaded.bindings == (manifest.plugins[0].binding,)
    importer.assert_called_once_with("grafy_test_system_plugin")


def test_manifest_serialization_is_canonical_and_atomic(tmp_path: Path) -> None:
    binding = _binding("f" * 64)
    manifest = _manifest(binding)
    path = tmp_path / "deployment" / "system-plugins.json"
    path.parent.mkdir()
    path.write_text("stale", encoding="utf-8")

    written = write_system_plugin_deployment_manifest(path, manifest)

    assert written == path
    assert path.read_bytes() == manifest.canonical_json_bytes()
    assert SystemPluginDeploymentManifest.from_json_bytes(path.read_bytes()) == manifest
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_file_loader_wraps_invalid_json_with_path_context(tmp_path: Path) -> None:
    path = tmp_path / "system-plugins.json"
    path.write_text('{"plugins":[{"unknown":true}]}', encoding="utf-8")

    with pytest.raises(
        SystemPluginDeploymentError,
        match=f"Invalid System Plugin deployment manifest {path}",
    ) as raised:
        load_system_plugin_deployment_file(path)

    assert isinstance(raised.value.__cause__, ValidationError)


def test_manifest_rejects_duplicate_slugs() -> None:
    binding = _binding("f" * 64)
    entry = _manifest(binding).plugins[0]

    with pytest.raises(ValidationError, match="slugs must be unique"):
        SystemPluginDeploymentManifest(plugins=(entry, entry))


def test_manifest_rejects_duplicate_loader_targets() -> None:
    binding = _binding("f" * 64)
    other_binding = _binding(
        "f" * 64,
        catalog=PluginCatalogManifest.from_plugin(ARITHMETIC),
        loader_target=binding.loader_target,
    ).model_copy(update={"release_id": uuid4()})
    first = _manifest(binding).plugins[0]
    second = SystemPluginDeploymentEntry(
        binding=other_binding,
        distribution_name="grafy-plugin-other",
        loader_target=other_binding.loader_target,
        host_build_digest=other_binding.host_build_digest,
    )

    with pytest.raises(ValidationError, match="loader targets must be unique"):
        SystemPluginDeploymentManifest(plugins=(first, second))


def test_manifest_entry_requires_binding_loader_and_build_identity() -> None:
    binding = _binding("f" * 64)

    with pytest.raises(ValidationError, match="loader target must match"):
        SystemPluginDeploymentEntry(
            binding=binding,
            distribution_name=_DISTRIBUTION_NAME,
            loader_target="grafy_test_system_plugin:OTHER",
            host_build_digest=binding.host_build_digest,
        )
    with pytest.raises(ValidationError, match="build digest must match"):
        SystemPluginDeploymentEntry(
            binding=binding,
            distribution_name=_DISTRIBUTION_NAME,
            loader_target=binding.loader_target,
            host_build_digest="e" * 64,
        )


def test_distribution_digest_is_canonical_across_file_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed, _ = _installed_tree(tmp_path)
    reversed_files = _InstalledDistribution(
        tmp_path,
        tuple(str(path) for path in reversed(installed.files)),
    )
    lookup = Mock(
        side_effect=(cast(Distribution, installed), cast(Distribution, reversed_files))
    )
    monkeypatch.setattr(system_plugin_loader, "distribution", lookup)

    first = installed_distribution_build_digest(_DISTRIBUTION_NAME)
    second = installed_distribution_build_digest(_DISTRIBUTION_NAME)

    assert first == second


def test_loader_rejects_installed_build_digest_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed, _ = _installed_tree(tmp_path)
    monkeypatch.setattr(
        system_plugin_loader,
        "distribution",
        Mock(return_value=cast(Distribution, installed)),
    )

    with pytest.raises(SystemPluginDeploymentError, match="build digest mismatch"):
        load_system_plugin_deployment(_manifest(_binding("f" * 64)))


@pytest.mark.parametrize(
    ("declared_file", "expected"),
    [
        ("../outside.py", "unsafe file path"),
        ("missing.py", "is missing"),
    ],
)
def test_loader_rejects_unsafe_or_missing_distribution_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared_file: str,
    expected: str,
) -> None:
    installed = _InstalledDistribution(tmp_path, (declared_file,))
    monkeypatch.setattr(
        system_plugin_loader,
        "distribution",
        Mock(return_value=cast(Distribution, installed)),
    )

    with pytest.raises(SystemPluginDeploymentError, match=expected):
        load_system_plugin_deployment(_manifest(_binding("f" * 64)))


def test_loader_rejects_symlinked_distribution_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.py"
    target.write_text("# target\n", encoding="utf-8")
    (tmp_path / "plugin.py").symlink_to(target)
    installed = _InstalledDistribution(tmp_path, ("plugin.py",))
    monkeypatch.setattr(
        system_plugin_loader,
        "distribution",
        Mock(return_value=cast(Distribution, installed)),
    )

    with pytest.raises(SystemPluginDeploymentError, match="symbolic link"):
        load_system_plugin_deployment(_manifest(_binding("f" * 64)))


def test_loader_rejects_missing_distribution_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = PackageNotFoundError(_DISTRIBUTION_NAME)
    monkeypatch.setattr(
        system_plugin_loader,
        "distribution",
        Mock(side_effect=missing),
    )

    with pytest.raises(
        SystemPluginDeploymentError,
        match=r"System Plugin 'text' distribution .* is not installed",
    ) as raised:
        load_system_plugin_deployment(_manifest(_binding("f" * 64)))

    assert raised.value.__cause__ is missing


def test_loader_preserves_import_failure_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, _, _ = _exact_manifest(tmp_path, monkeypatch)
    failure = RuntimeError("import failed")
    monkeypatch.setattr(
        system_plugin_loader,
        "import_module",
        Mock(side_effect=failure),
    )

    with pytest.raises(
        SystemPluginDeploymentError,
        match=r"Failed to import System Plugin 'text' loader target",
    ) as raised:
        load_system_plugin_deployment(manifest)

    assert raised.value.__cause__ is failure


def test_loader_rejects_module_outside_declared_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, module, _ = _exact_manifest(tmp_path, monkeypatch)
    outside = tmp_path.parent / "outside-system-plugin.py"
    outside.write_text("# outside\n", encoding="utf-8")
    module.__file__ = str(outside)

    with pytest.raises(SystemPluginDeploymentError, match="is not owned"):
        load_system_plugin_deployment(manifest)


def test_loader_rejects_non_plugin_and_slug_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, module, _ = _exact_manifest(tmp_path, monkeypatch)
    module.PLUGIN = object()  # type: ignore[attr-defined]

    with pytest.raises(SystemPluginDeploymentError, match="expected Plugin"):
        load_system_plugin_deployment(manifest)

    module.PLUGIN = Plugin(slug="builtin.other", title="Other")  # type: ignore[attr-defined]
    with pytest.raises(SystemPluginDeploymentError, match="expected 'text'"):
        load_system_plugin_deployment(manifest)


def test_loader_rejects_catalog_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, _, _, _ = _exact_manifest(tmp_path, monkeypatch)
    changed_catalog = manifest.plugins[0].binding.catalog.model_copy(
        update={"title": "Changed title"}
    )
    changed_binding = _binding(
        manifest.plugins[0].host_build_digest,
        catalog=changed_catalog,
    )

    with pytest.raises(SystemPluginDeploymentError, match="catalog does not match"):
        load_system_plugin_deployment(_manifest(changed_binding))


_WHEEL_METADATA = (
    b"Metadata-Version: 2.4\nName: grafy-plugin-test-system\nVersion: 1.0\n"
)


def _wheel_entries() -> tuple[tuple[str, bytes], ...]:
    return (
        (
            "grafy_plugin_test_system-1.0.dist-info/METADATA",
            _WHEEL_METADATA,
        ),
        ("grafy_test_system_plugin.py", b"# exact wheel plugin bytes\n"),
    )


def _write_wheel(
    tmp_path: Path,
    *,
    entries: tuple[tuple[str, bytes], ...] = _wheel_entries(),
    raw_infos: tuple[ZipInfo, ...] = (),
) -> Path:
    wheel_path = tmp_path / "grafy_plugin_test_system-1.0-py3-none-any.whl"
    wheel_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(wheel_path, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
        for info in raw_infos:
            archive.writestr(info, b"raw entry")
    return wheel_path


def _write_encrypted_wheel(tmp_path: Path) -> Path:
    """Write a wheel whose single entry declares the encrypted flag bit.

    ``zipfile`` clears ``flag_bits`` while writing, so the bit is set directly
    in the local and central directory headers.
    """
    wheel_path = tmp_path / "grafy_plugin_test_system-1.0-py3-none-any.whl"
    wheel_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(wheel_path, "w") as archive:
        archive.writestr("grafy_test_system_plugin.py", b"encrypted entry")
    data = bytearray(wheel_path.read_bytes())
    local_header = data.find(b"\x50\x4b\x03\x04")
    data[local_header + 6] |= 0x01
    central_header = data.find(b"\x50\x4b\x01\x02")
    data[central_header + 8] |= 0x01
    wheel_path.write_bytes(bytes(data))
    return wheel_path


def test_wheel_digest_rejects_unsafe_or_nonregular_entries(
    tmp_path: Path,
) -> None:
    traversal_wheel = _write_wheel(
        tmp_path / "traversal",
        entries=_wheel_entries() + (("../outside.py", b"traversal"),),
    )
    duplicate_wheel = _write_wheel(
        tmp_path / "duplicate",
        entries=(
            (
                "grafy_plugin_test_system-1.0.dist-info/METADATA",
                _WHEEL_METADATA,
            ),
            ("grafy_test_system_plugin.py", b"first"),
            ("grafy_test_system_plugin.py", b"second"),
        ),
    )
    symlink_info = ZipInfo("grafy_test_system_plugin.py")
    symlink_info.external_attr = (stat.S_IFLNK | 0o755) << 16
    symlink_wheel = _write_wheel(
        tmp_path / "symlink",
        entries=(),
        raw_infos=(symlink_info,),
    )
    encrypted_wheel = _write_encrypted_wheel(tmp_path / "encrypted")

    for wheel, expected in (
        (traversal_wheel, "unsafe file path"),
        (duplicate_wheel, "duplicate file path"),
        (symlink_wheel, "is not regular"),
        (encrypted_wheel, "is encrypted"),
    ):
        with pytest.raises(
            SystemPluginDeploymentError,
            match=expected,
        ):
            wheel_distribution_build_digest(wheel, _DISTRIBUTION_NAME)


def test_wheel_digest_rejects_wrong_distribution_metadata(
    tmp_path: Path,
) -> None:
    entries = (
        (
            "grafy_plugin_test_system-1.0.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: grafy-plugin-other\nVersion: 1.0\n",
        ),
        ("grafy_test_system_plugin.py", b"# exact wheel plugin bytes\n"),
    )
    wheel = _write_wheel(tmp_path, entries=entries)
    with pytest.raises(
        SystemPluginDeploymentError,
        match=r"wheel metadata declares 'grafy-plugin-other'",
    ):
        wheel_distribution_build_digest(wheel, _DISTRIBUTION_NAME)


def test_wheel_and_installed_digests_share_one_canonical_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel = _write_wheel(tmp_path / "wheel")
    wheel_digest = wheel_distribution_build_digest(wheel, _DISTRIBUTION_NAME)

    installed_root = tmp_path / "installed"
    installed_root.mkdir()
    for name, content in _wheel_entries():
        destination = installed_root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    record_file = installed_root / "grafy_plugin_test_system-1.0.dist-info" / "RECORD"
    record_file.write_text("grafy_test_system_plugin.py,,\n", encoding="utf-8")
    installed = _InstalledDistribution(
        installed_root,
        (
            "grafy_plugin_test_system-1.0.dist-info/METADATA",
            "grafy_plugin_test_system-1.0.dist-info/RECORD",
            "grafy_test_system_plugin.py",
        ),
    )
    monkeypatch.setattr(
        system_plugin_loader,
        "distribution",
        Mock(return_value=cast(Distribution, installed)),
    )

    # Installer-generated files (RECORD here, bytecode/caches in general) must
    # not create a false mismatch between the two digest sources.
    assert installed_distribution_build_digest(_DISTRIBUTION_NAME) == wheel_digest
