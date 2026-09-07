from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginNodeContract,
)
from grafy_core.runtime.plugin_loader import WORKSPACE_PLUGIN_LOADER_TARGET

from grafy_api.plugins.profiles import PYTHON_UV_BASE_IMAGE_DIGEST, runtime_profile
from grafy_api.plugins.publication.oci import _dockerfile
from grafy_api.plugins.publication.source import VerifiedPluginCandidate
from grafy_core.domain.plugin_releases import PluginCapabilityManifest


def test_runtime_profile_is_pinned_and_unknown_names_are_rejected() -> None:
    profile = runtime_profile("python-uv")

    assert profile.python_version == "3.14"
    assert profile.base_image_digest == PYTHON_UV_BASE_IMAGE_DIGEST
    assert profile.pinned_base_image.endswith(f"@sha256:{PYTHON_UV_BASE_IMAGE_DIGEST}")
    assert profile.cpu_count == 1.0
    assert profile.memory_bytes == 512 * 1_024 * 1_024
    assert profile.pid_limit == 128

    with pytest.raises(ValueError, match="Unknown Plugin runtime profile"):
        runtime_profile("team-image:latest")


def test_dockerfile_sync_uses_bundled_plugin_wheels() -> None:
    dockerfile = _dockerfile(
        runtime_profile("python-uv"),
        source_digest="1" * 64,
        contract_digest="2" * 64,
        profile_digest="3" * 64,
        loader_manifest_digest="4" * 64,
    )

    assert (
        "RUN uv sync --locked --no-dev --no-editable \\\n"
        "    --find-links /opt/grafy/plugin/wheels \\\n"
        "    && test -x /opt/grafy/plugin/.venv/bin/python"
    ) in dockerfile
    assert (
        "COPY --chmod=0444 plugin-loader.json /opt/grafy/plugin/plugin-loader.json"
    ) in dockerfile
    assert (
        "/opt/grafy/plugin/.venv/bin/python -I -c \"from pathlib import Path; "
        "from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest; "
        "PluginGuestLoaderManifest.from_json_bytes("
        "Path('/opt/grafy/plugin/plugin-loader.json').read_bytes())\""
    ) in dockerfile
    assert 'io.grafy.plugin.loader.digest="sha256:' + "4" * 64 in dockerfile


def test_native_capabilities_require_exact_deployment_owned_profile_image() -> None:
    with pytest.raises(ValueError, match="requires an exact deployment-owned"):
        runtime_profile("python-uv-gdal")

    profile = runtime_profile(
        "python-uv-gdal",
        native_base_image="registry.example/grafy-python-gdal",
        native_base_image_digest="d" * 64,
    )

    assert profile.pinned_base_image == (
        "registry.example/grafy-python-gdal@sha256:" + "d" * 64
    )
    assert profile.native_capabilities == frozenset(
        {PluginRuntimeCapability.NATIVE_GDAL}
    )
    dockerfile = _dockerfile(
        profile,
        source_digest="1" * 64,
        contract_digest="2" * 64,
        profile_digest="3" * 64,
        loader_manifest_digest="4" * 64,
    )
    assert dockerfile.startswith(f"FROM {profile.pinned_base_image}\n")
    assert f'io.grafy.plugin.base.digest="sha256:{"d" * 64}"' in dockerfile
    assert 'io.grafy.plugin.profile.digest="sha256:' + "3" * 64 in dockerfile
    assert "apt-get" not in dockerfile


def test_verified_candidate_is_the_immutable_oci_build_identity() -> None:
    catalog = PluginCatalogManifest(
        slug="notes",
        title="Notes",
        nodes=(
            PluginNodeContract(
                operator_id="notes.echo",
                operator_version=1,
                title="Echo",
                description="Echo",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
    )
    candidate = VerifiedPluginCandidate(
        catalog=catalog,
        capabilities=PluginCapabilityManifest(),
        loader_target=WORKSPACE_PLUGIN_LOADER_TARGET,
        source_archive=b"frozen source",
        lock_digest="1" * 64,
        runtime_profile="python-uv",
    )

    assert candidate.source_digest == sha256(b"frozen source").hexdigest()
    with pytest.raises(FrozenInstanceError):
        candidate.loader_target = "other_plugin:PLUGIN"
