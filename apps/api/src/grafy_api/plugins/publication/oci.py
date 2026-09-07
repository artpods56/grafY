"""Build immutable Plugin images from verified source and a runtime profile."""

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
import tomllib
from typing import cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.domain.plugin_releases import (
    PluginRuntimeArtifact,
    plugin_protocol_digest,
)
from grafy_core.ports.storage import FileStoragePort, SaveFileCommand
from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest

from grafy_api.plugins.profiles import PluginRuntimeProfile
from grafy_api.plugins.publication.source import (
    VerifiedPluginCandidate,
    unpack_source_snapshot,
)


class PluginOciBuildError(RuntimeError):
    """The frozen Plugin source could not produce a verified OCI artifact."""


@dataclass(frozen=True, slots=True)
class _BuiltOciArchive:
    content: bytes
    archive_digest: str
    manifest_digest: str
    config_digest: str


class PluginOciImageBuilder:
    """Build and store one immutable OCI archive from exact frozen source."""

    def __init__(
        self,
        storage: FileStoragePort,
        *,
        bucket: str,
        profile: PluginRuntimeProfile,
        docker_binary: str = "docker",
    ) -> None:
        self._storage = storage
        self._bucket = bucket
        self._profile = profile
        self._docker_binary = docker_binary

    async def build_and_store(
        self,
        *,
        candidate: VerifiedPluginCandidate,
    ) -> PluginRuntimeArtifact:
        source_digest = candidate.source_digest
        contract_digest = candidate.contract_digest
        profile_digest = candidate.profile_digest
        try:
            loader_manifest = PluginGuestLoaderManifest(
                slug=candidate.catalog.slug,
                loader_target=candidate.loader_target,
            )
        except ValidationError as exc:
            raise PluginOciBuildError(
                f"Plugin {candidate.catalog.slug!r} has an invalid guest loader target"
            ) from exc
        built = await asyncio.to_thread(
            self._build,
            candidate.catalog.slug,
            loader_manifest,
            candidate.source_archive,
            source_digest,
            contract_digest,
            profile_digest,
        )
        object_key = (
            f"plugin-releases/{candidate.catalog.slug}/runtime/"
            f"{built.archive_digest}.oci.tar"
        )
        artifact = PluginRuntimeArtifact(
            object_key=object_key,
            archive_digest=built.archive_digest,
            manifest_digest=built.manifest_digest,
            config_digest=built.config_digest,
        )
        await self._save_archive(artifact, built.content)
        return artifact

    def _build(
        self,
        slug: str,
        loader_manifest: PluginGuestLoaderManifest,
        source_archive: bytes,
        source_digest: str,
        contract_digest: str,
        profile_digest: str,
    ) -> _BuiltOciArchive:
        with TemporaryDirectory(prefix="grafy-plugin-oci-build-") as temporary:
            context = Path(temporary)
            source = context / "source"
            source.mkdir()
            unpack_source_snapshot(source_archive, source)
            _validate_locked_package_sources(source)
            (context / "plugin-loader.json").write_bytes(
                loader_manifest.canonical_json_bytes()
            )
            build_identity = sha256(
                (
                    f"{source_digest}:{contract_digest}:{profile_digest}:"
                    f"{self._profile.base_image_digest}:"
                    f"{plugin_protocol_digest()}:{loader_manifest.digest}"
                ).encode("ascii")
            ).hexdigest()
            dockerfile = context / "Dockerfile"
            dockerfile.write_text(
                _dockerfile(
                    self._profile,
                    source_digest=source_digest,
                    contract_digest=contract_digest,
                    profile_digest=profile_digest,
                    loader_manifest_digest=loader_manifest.digest,
                ),
                encoding="utf-8",
            )
            output = context / "image.oci.tar"
            command = (
                self._docker_binary,
                "buildx",
                "build",
                "--pull",
                "--provenance=false",
                "--sbom=false",
                "--build-arg",
                "SOURCE_DATE_EPOCH=0",
                "--tag",
                f"grafy-plugin-{slug}-{build_identity[:16]}:latest",
                "--output",
                f"type=oci,dest={output}",
                str(context),
            )
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1_800,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PluginOciBuildError("Plugin OCI build could not run") from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()[-4_000:]
                raise PluginOciBuildError(
                    f"Plugin OCI build failed with exit code "
                    f"{completed.returncode}: {detail}"
                )
            content = output.read_bytes()
            manifest_digest, config_digest = _oci_archive_digests(content)
            return _BuiltOciArchive(
                content=content,
                archive_digest=sha256(content).hexdigest(),
                manifest_digest=manifest_digest,
                config_digest=config_digest,
            )

    async def _save_archive(
        self,
        artifact: PluginRuntimeArtifact,
        content: bytes,
    ) -> None:
        try:
            stored = await self._storage.save(
                SaveFileCommand(
                    bucket=self._bucket,
                    path=artifact.object_key,
                    stream=BytesIO(content),
                    content_type="application/vnd.oci.image.layout.v1.tar",
                    metadata={
                        "source": "plugin-runtime",
                        "sha256": artifact.archive_digest,
                    },
                )
            )
        except ObjectAlreadyExistsError:
            existing = await self._storage.load(self._bucket, artifact.object_key)
            try:
                existing_digest = sha256(existing.read()).hexdigest()
            finally:
                existing.close()
            if existing_digest != artifact.archive_digest:
                raise PluginOciBuildError(
                    "Stored Plugin OCI archive does not match its object key"
                )
            return
        if stored.sha256 != artifact.archive_digest:
            raise PluginOciBuildError(
                "Stored Plugin OCI archive changed while being written"
            )


def _dockerfile(
    profile: PluginRuntimeProfile,
    *,
    source_digest: str,
    contract_digest: str,
    profile_digest: str,
    loader_manifest_digest: str,
) -> str:
    return f"""FROM {profile.pinned_base_image}
ARG SOURCE_DATE_EPOCH=0
ENV HOME=/tmp/home \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \\
    UV_CACHE_DIR=/tmp/uv-cache \\
    UV_LINK_MODE=copy \\
    UV_NO_PROGRESS=1
WORKDIR /opt/grafy/plugin
COPY source/ /opt/grafy/plugin/
COPY --chmod=0444 plugin-loader.json /opt/grafy/plugin/plugin-loader.json
RUN uv sync --locked --no-dev --no-editable \\
    --find-links /opt/grafy/plugin/wheels \\
    && test -x /opt/grafy/plugin/.venv/bin/python \\
    && test -r /opt/grafy/plugin/plugin-loader.json \\
    && /opt/grafy/plugin/.venv/bin/python -I -c "from pathlib import Path; from grafy_core.runtime.plugin_loader import PluginGuestLoaderManifest; PluginGuestLoaderManifest.from_json_bytes(Path('/opt/grafy/plugin/plugin-loader.json').read_bytes())" \\
    && rm -rf /tmp/uv-cache
LABEL org.opencontainers.image.source.digest="sha256:{source_digest}" \\
      io.grafy.plugin.runtime="1" \\
      io.grafy.plugin.contract.digest="sha256:{contract_digest}" \\
      io.grafy.plugin.profile.digest="sha256:{profile_digest}" \\
      io.grafy.plugin.base.digest="sha256:{profile.base_image_digest}" \\
      io.grafy.plugin.protocol.digest="sha256:{plugin_protocol_digest()}" \\
      io.grafy.plugin.loader.digest="sha256:{loader_manifest_digest}"
USER 65532:65532
ENTRYPOINT ["/opt/grafy/plugin/.venv/bin/python", "-I"]
"""


def _validate_locked_package_sources(source: Path) -> None:
    allowed_hosts = {"pypi.org", "files.pythonhosted.org"}
    for name in ("pyproject.toml", "uv.lock"):
        document = tomllib.loads((source / name).read_text(encoding="utf-8"))
        values: list[object] = [document]
        while values:
            value = values.pop()
            if isinstance(value, dict):
                values.extend(cast(dict[object, object], value).values())
                continue
            if isinstance(value, list):
                values.extend(cast(list[object], value))
                continue
            if not isinstance(value, str) or not value.startswith(
                ("http://", "https://")
            ):
                continue
            parsed = urlsplit(value)
            if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
                raise PluginOciBuildError(
                    f"Plugin dependency source {value!r} is not approved"
                )


def _oci_archive_digests(content: bytes) -> tuple[str, str]:
    try:
        with tarfile.open(fileobj=BytesIO(content), mode="r:") as archive:
            index_member = archive.getmember("index.json")
            index_stream = archive.extractfile(index_member)
            if index_stream is None:
                raise PluginOciBuildError("OCI archive has no readable index")
            index = json.loads(index_stream.read())
            if not isinstance(index, dict):
                raise PluginOciBuildError("OCI archive index must be an object")
            manifests = cast(dict[str, object], index).get("manifests")
            if not isinstance(manifests, list):
                raise PluginOciBuildError(
                    "OCI archive must contain exactly one image manifest"
                )
            raw_manifests = cast(list[object], manifests)
            if len(raw_manifests) != 1:
                raise PluginOciBuildError(
                    "OCI archive must contain exactly one image manifest"
                )
            descriptor = raw_manifests[0]
            if not isinstance(descriptor, dict):
                raise PluginOciBuildError("OCI image descriptor must be an object")
            raw_descriptor = cast(dict[str, object], descriptor)
            manifest_digest = _sha256_digest_value(raw_descriptor.get("digest"))
            if raw_descriptor.get("mediaType") != (
                "application/vnd.oci.image.manifest.v1+json"
            ):
                raise PluginOciBuildError("OCI archive has an unsupported manifest")
            manifest_stream = archive.extractfile(f"blobs/sha256/{manifest_digest}")
            if manifest_stream is None:
                raise PluginOciBuildError("OCI archive manifest blob is missing")
            manifest_bytes = manifest_stream.read()
            if sha256(manifest_bytes).hexdigest() != manifest_digest:
                raise PluginOciBuildError("OCI archive manifest digest is invalid")
            manifest = json.loads(manifest_bytes)
            if not isinstance(manifest, dict):
                raise PluginOciBuildError("OCI image manifest must be an object")
            config = cast(dict[str, object], manifest).get("config")
            if not isinstance(config, dict):
                raise PluginOciBuildError("OCI image manifest has no config")
            config_digest = _sha256_digest_value(
                cast(dict[str, object], config).get("digest")
            )
            config_stream = archive.extractfile(f"blobs/sha256/{config_digest}")
            if config_stream is None:
                raise PluginOciBuildError("OCI archive config blob is missing")
            if sha256(config_stream.read()).hexdigest() != config_digest:
                raise PluginOciBuildError("OCI archive config digest is invalid")
            return manifest_digest, config_digest
    except (KeyError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise PluginOciBuildError(
            "Plugin runtime artifact is not a valid OCI archive"
        ) from exc


def _sha256_digest_value(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise PluginOciBuildError("OCI descriptor must contain a SHA-256 digest")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise PluginOciBuildError("OCI descriptor SHA-256 digest is invalid")
    return digest


__all__ = [
    "PluginOciBuildError",
    "PluginOciImageBuilder",
]
