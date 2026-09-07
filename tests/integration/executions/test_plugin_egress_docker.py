import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from typing import cast
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import ArtifactRef, InMemoryUnitOfWork, NodeInput, NodeOutput
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginExecutionPolicy,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.nodes import NodeExecutionContext
from grafy_core.runtime.plugin_invocation import (
    PluginReleaseNodeConfig,
    PluginReleaseNode,
)
from grafy_storage import LocalFileObjectStore

from grafy_api.network_policy import (
    NetworkAccessPlane,
    NetworkAccessProfile,
    NetworkPolicy,
    NetworkProfileAssignment,
    NetworkProfileMode,
)
from grafy_api.plugin_egress import (
    PluginEgressBrokerPolicy,
    PluginEgressDestination,
    PluginEgressProtocol,
)
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.source import PluginDirectoryPublisher
from grafy_api.v1.routes.executions.runtime.plugin_artifacts import (
    ArtifactBundlePluginInvoker,
)
from grafy_api.v1.routes.executions.runtime.plugin_docker import DockerPluginRuntime
from grafy_api.v1.routes.executions.runtime.plugin_sandbox import (
    PluginSandboxScopeId,
    activate_plugin_sandbox_scope,
    reset_plugin_sandbox_scope,
)


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000952")


@dataclass
class ReleaseLookup:
    release: InstalledPluginRelease

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        if (
            scope is self.release.scope
            and workspace_id == self.release.workspace_id
            and slug == self.release.slug
            and revision == self.release.revision
        ):
            return self.release
        return None

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        del workspace_id, slug, revision
        return None

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None:
        del slug, revision
        return None

    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]:
        if self.release.runtime_artifact is None:
            return []
        return [self.release.runtime_artifact]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    completed = subprocess.run(
        ("docker", "version", "--format", "{{.Server.Version}}"),
        check=False,
        capture_output=True,
        timeout=10,
    )
    return completed.returncode == 0


def _network_egress_plugin(repository: Path, destination: Path) -> Path:
    source = repository / "examples" / "plugin-notes"
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".venv", "build", "dist", "__pycache__"),
    )
    declaration = destination / "src" / "grafy_plugin" / "declaration.py"
    declaration.write_text(
        declaration.read_text(encoding="utf-8")
        .replace(
            "from grafy_core.plugins import Plugin",
            (
                "from grafy_core.domain.plugin_capabilities import "
                "PluginRuntimeCapability\n"
                "from grafy_core.plugins import Plugin"
            ),
        )
        .replace(
            'PLUGIN = Plugin(slug="notes", title="Notes")',
            (
                'PLUGIN = Plugin(slug="notes", title="Notes", capabilities=('
                "PluginRuntimeCapability.NETWORK_EGRESS,))"
            ),
        ),
        encoding="utf-8",
    )
    nodes = destination / "src" / "grafy_plugin" / "nodes.py"
    nodes.write_text(
        nodes.read_text(encoding="utf-8")
        + """

import urllib.request

from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability


class NetworkProbeInput(NodeInput):
    pass


class NetworkProbeOutput(NodeOutput):
    text: Annotated[TextValue, OutPort(TEXT_VALUE)]


@PLUGIN.function_node(
    operator_id="notes.network.probe",
    version=1,
    title="Network probe",
    required_capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
    cache_policy=NodeCachePolicy.NEVER,
)
async def network_probe(
    _config: NoConfig,
    _inputs: NetworkProbeInput,
) -> NetworkProbeOutput:
    try:
        with urllib.request.urlopen("http://example.com/", timeout=10) as response:
            body = response.read(4_096).decode("utf-8")
    except Exception as exc:
        body = f"{type(exc).__name__}: {exc}"
    return NetworkProbeOutput(text=TextValue(value=body))
""",
        encoding="utf-8",
    )
    plugin_init = destination / "src" / "grafy_plugin" / "__init__.py"
    plugin_init.write_text(
        plugin_init.read_text(encoding="utf-8")
        .replace(
            "from grafy_plugin.nodes import render_summary, summarize_table",
            (
                "from grafy_plugin.nodes import (\n"
                "    network_probe,\n"
                "    render_summary,\n"
                "    summarize_table,\n"
                ")"
            ),
        )
        .replace(
            '__all__ = ["PLUGIN", "render_summary", "summarize_table"]',
            (
                '__all__ = ["PLUGIN", "network_probe", "render_summary", '
                '"summarize_table"]'
            ),
        ),
        encoding="utf-8",
    )
    wheels = destination / "wheels"
    for wheel in wheels.glob("grafy_core-*.whl"):
        wheel.unlink()
    subprocess.run(
        (
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(wheels),
            str(repository / "libs" / "core"),
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run(
        (
            "uv",
            "lock",
            "--find-links",
            "wheels",
            "--refresh-package",
            "grafy-core",
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=destination,
    )
    return destination


@pytest.mark.asyncio
async def test_docker_runtime_routes_historical_network_egress_through_live_broker(
    tmp_path: Path,
) -> None:
    if not _docker_available():
        pytest.skip("local Docker daemon is unavailable")

    repository = Path(__file__).resolve().parents[3]
    registry_name = f"grafy-egress-registry-{uuid4().hex}"
    broker_tag: str | None = None
    broker_reference: str | None = None
    plugin_image: str | None = None
    runtime: DockerPluginRuntime | None = None
    scope: PluginSandboxScopeId | None = None
    scope_token = None
    guest_networks: tuple[str, ...] = ()
    try:
        subprocess.run(
            (
                "docker",
                "run",
                "--detach",
                "--name",
                registry_name,
                "--publish",
                "127.0.0.1::5000",
                "registry:2",
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        registry = json.loads(
            subprocess.run(
                ("docker", "inspect", registry_name),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )[0]
        registry_port = registry["NetworkSettings"]["Ports"]["5000/tcp"][0]["HostPort"]
        assert isinstance(registry_port, str)
        broker_repository = f"localhost:{registry_port}/grafy/plugin-egress-broker"
        broker_tag = f"{broker_repository}:integration"
        subprocess.run(
            (
                "docker",
                "build",
                "--file",
                str(repository / "infra/docker/plugin-egress-broker.Dockerfile"),
                "--tag",
                broker_tag,
                str(repository),
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        subprocess.run(
            ("docker", "push", broker_tag),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        repo_digests = json.loads(
            subprocess.run(
                (
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{json .RepoDigests}}",
                    broker_tag,
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
        broker_reference = next(
            digest
            for digest in repo_digests
            if digest.startswith(f"{broker_repository}@sha256:")
        )

        plugin_project = _network_egress_plugin(
            repository,
            tmp_path / "plugin-network-egress",
        )
        verified = await asyncio.to_thread(
            PluginDirectoryPublisher(
                (tmp_path,),
                runtime_profile="python-uv",
            ).verify,
            plugin_project,
        )
        assert verified.capabilities.capabilities == (
            PluginRuntimeCapability.NETWORK_EGRESS,
        )
        source_digest = sha256(verified.source_archive).hexdigest()
        contract_digest = plugin_contract_digest(verified.catalog)
        profile_digest = plugin_profile_digest(verified.runtime_profile)
        storage = LocalFileObjectStore(tmp_path / "objects")
        profile = runtime_profile(verified.runtime_profile)
        artifact = await PluginOciImageBuilder(
            storage,
            bucket="runtime-test",
            profile=profile,
        ).build_and_store(
            candidate=verified,
        )
        plugin_image = f"sha256:{artifact.manifest_digest}"
        # Construct the release directly because this fixture models a persisted
        # historical catalog that predates HTTP egress contracts. The current
        # publication workflow rejects a newly published equivalent.
        release_record = PluginRelease(
            slug=verified.catalog.slug,
            revision=1,
            catalog=verified.catalog,
            contract_digest=contract_digest,
            capabilities=verified.capabilities,
            capability_digest=verified.capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=profile_digest,
            source_object_key="plugin-releases/notes/source.tar.gz",
            source_digest=source_digest,
            lock_digest=verified.lock_digest,
            runtime_profile=verified.runtime_profile,
            loader_target=verified.loader_target,
            runtime_image_digest=artifact.manifest_digest,
            runtime_artifact=artifact,
            published_by_user_id=WORKSPACE_ID,
        )
        release = InstalledPluginRelease(
            release=release_record,
            installation=PluginInstallation.from_release(
                release_record,
                namespace=PluginReleaseNamespace(
                    scope=PluginReleaseScope.WORKSPACE,
                    workspace_id=WORKSPACE_ID,
                ),
                execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
                installed_by_user_id=WORKSPACE_ID,
                installed_by_platform_actor=None,
            ),
        )
        probe_destination = PluginEgressDestination(
            protocol=PluginEgressProtocol.HTTP,
            host="example.com",
            port=80,
        )
        # The probe node declares NETWORK_EGRESS without an http_egress
        # contract, so it needs a curated legacy-compatibility profile
        # (spec §17.2) allowing its exact plain-HTTP origin.
        legacy_egress = NetworkAccessProfile(
            name="legacy-egress",
            plane=NetworkAccessPlane.PLUGIN_EXECUTION,
            mode=NetworkProfileMode.CURATED,
            https_only=False,
            allowed_origins=(probe_destination,),
        )
        network_policy = NetworkPolicy(
            profiles={(legacy_egress.plane, legacy_egress.name): legacy_egress},
            assignments=(
                NetworkProfileAssignment(
                    plane=legacy_egress.plane,
                    profile=legacy_egress.name,
                    scope=PluginReleaseScope.WORKSPACE,
                    workspace_id=WORKSPACE_ID,
                    slug="notes",
                ),
            ),
        )
        runtime = DockerPluginRuntime(
            releases=ReleaseLookup(release),
            storage=storage,
            bucket="runtime-test",
            profile=profile,
            scratch_root=tmp_path / "scratch",
            egress_policy=PluginEgressBrokerPolicy(
                broker_image=broker_reference,
                destinations=(probe_destination,),
            ),
            network_policy=network_policy,
        )
        await runtime.check_ready()
        unit_of_work = InMemoryUnitOfWork()
        invoker = ArtifactBundlePluginInvoker(
            unit_of_work=unit_of_work,
            runner=runtime,
            scratch=runtime,
            storage=storage,
            bucket="runtime-test",
            storage_backend="local",
        )
        contract = next(
            node
            for node in release.catalog.nodes
            if node.operator_id == "notes.network.probe"
        )
        node: PluginReleaseNode[
            PluginReleaseNodeConfig,
            NodeInput,
            NodeOutput,
        ] = PluginReleaseNode(release, contract, invoker)
        scope = PluginSandboxScopeId.new()
        scope_token = activate_plugin_sandbox_scope(scope)
        output = await node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                node_id="network-egress-probe",
            ),
            node.config_contract.model.model_validate({}),
            node.input_contract.model.model_validate({}),
        )
        text_ref = cast(ArtifactRef, output.__dict__["text"])
        async with unit_of_work as entered:
            text_artifact = await entered.artifacts.get(
                WORKSPACE_ID,
                text_ref.artifact_id,
            )
        assert text_artifact is not None
        assert text_artifact.inline_payload is not None
        response_body = text_artifact.inline_payload["value"]
        assert isinstance(response_body, str)
        assert "Example Domain" in response_body

        containers = json.loads(
            subprocess.run(
                (
                    "docker",
                    "inspect",
                    *subprocess.run(
                        (
                            "docker",
                            "ps",
                            "-q",
                            "--filter",
                            f"label=io.grafy.plugin.scope={scope.value}",
                        ),
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    ).stdout.split(),
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
        assert len(containers) == 2
        sandbox = next(
            container
            for container in containers
            if container["Config"]["Labels"].get("io.grafy.plugin.sandbox") == "1"
        )
        broker = next(
            container
            for container in containers
            if container["Config"]["Image"] == broker_reference
        )
        sandbox_networks = sandbox["NetworkSettings"]["Networks"]
        broker_networks = broker["NetworkSettings"]["Networks"]
        assert len(sandbox_networks) == 1
        assert set(sandbox_networks) < set(broker_networks)
        assert len(broker_networks) == 2
        guest_networks = tuple(broker_networks)
        network_documents = json.loads(
            subprocess.run(
                ("docker", "network", "inspect", *guest_networks),
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        )
        internal = next(network for network in network_documents if network["Internal"])
        outbound = next(
            network for network in network_documents if not network["Internal"]
        )
        assert set(internal["Containers"]) == {sandbox["Id"], broker["Id"]}
        assert set(outbound["Containers"]) == {broker["Id"]}
    finally:
        if runtime is not None and scope is not None:
            await runtime.close_scope(scope)
        if scope_token is not None:
            reset_plugin_sandbox_scope(scope_token)
        if guest_networks:
            remaining_networks = subprocess.run(
                ("docker", "network", "inspect", *guest_networks),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert remaining_networks.returncode != 0
        subprocess.run(
            ("docker", "rm", "--force", registry_name),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        removable_images = tuple(
            image
            for image in (plugin_image, broker_reference, broker_tag)
            if image is not None
        )
        if removable_images:
            subprocess.run(
                ("docker", "image", "rm", "--force", *removable_images),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
