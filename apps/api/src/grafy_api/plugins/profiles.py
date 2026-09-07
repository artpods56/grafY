"""Deployment-owned Plugin runtime profiles shared by building and execution."""

from dataclasses import dataclass

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import PLUGIN_INVOCATION_PROTOCOL


PYTHON_UV_BASE_IMAGE = "ghcr.io/astral-sh/uv:python3.14-bookworm-slim"
PYTHON_UV_BASE_IMAGE_DIGEST = (
    "7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1"
)


@dataclass(frozen=True, slots=True)
class PluginRuntimeProfile:
    """The single approved runtime profile for this deployment."""

    name: str = "python-uv"
    python_version: str = "3.14"
    base_image: str = PYTHON_UV_BASE_IMAGE
    base_image_digest: str = PYTHON_UV_BASE_IMAGE_DIGEST
    protocol_version: str = PLUGIN_INVOCATION_PROTOCOL
    cpu_count: float = 1.0
    memory_bytes: int = 512 * 1_024 * 1_024
    pid_limit: int = 128
    open_file_limit: int = 1_024
    scratch_bytes: int = 128 * 1_024 * 1_024
    native_capabilities: frozenset[PluginRuntimeCapability] = frozenset()

    @property
    def pinned_base_image(self) -> str:
        return f"{self.base_image}@sha256:{self.base_image_digest}"


def runtime_profile(
    name: str,
    *,
    native_base_image: str | None = None,
    native_base_image_digest: str | None = None,
) -> PluginRuntimeProfile:
    if name == "python-uv":
        if native_base_image is not None or native_base_image_digest is not None:
            raise ValueError(
                "The python-uv profile cannot override its pinned base image"
            )
        return PluginRuntimeProfile()
    native_profiles = {
        "python-uv-gdal": frozenset({PluginRuntimeCapability.NATIVE_GDAL}),
        "python-uv-tesseract": frozenset(
            {PluginRuntimeCapability.NATIVE_TESSERACT}
        ),
        "python-uv-gdal-tesseract": frozenset(
            {
                PluginRuntimeCapability.NATIVE_GDAL,
                PluginRuntimeCapability.NATIVE_TESSERACT,
            }
        ),
    }
    capabilities = native_profiles.get(name)
    if capabilities is None:
        raise ValueError(f"Unknown Plugin runtime profile {name!r}")
    if native_base_image is None or native_base_image_digest is None:
        raise ValueError(
            f"Native Plugin runtime profile {name!r} requires an exact "
            "deployment-owned base image and sha256 digest"
        )
    if (
        native_base_image.strip() == ""
        or "@" in native_base_image
        or len(native_base_image_digest) != 64
        or any(character not in "0123456789abcdef" for character in native_base_image_digest)
    ):
        raise ValueError("Native Plugin runtime base image configuration is invalid")
    return PluginRuntimeProfile(
        name=name,
        base_image=native_base_image,
        base_image_digest=native_base_image_digest,
        native_capabilities=capabilities,
    )
