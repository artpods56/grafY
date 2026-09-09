from collections.abc import Mapping
from pathlib import Path
from typing import Never
from uuid import UUID

import pytest

from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import InMemoryUnitOfWork
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginPortContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginExecutionPolicy,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.modules import GraphModuleExecutionResult
from grafy_storage import LocalFileObjectStore

from grafy_api.catalog import CatalogSnapshot
from grafy_api.plugins.runtime.admission import ReleaseExecutionAdmission
from grafy_api.v1.models import PluginReleasePinModel
from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_core.application.modules import ModuleLibraryService
from grafy_api.execution.requests import (
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.errors import GraphExecutionError


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000971")
TEXT_KEY = PluginArtifactTypeKey(id="scalar.text", schema_version=1)


class _UnusedModuleExecutor:
    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        _inputs: Mapping[str, object],
        /,
    ) -> GraphModuleExecutionResult:
        raise AssertionError("Admission parity test unexpectedly executed a module")


class _ReleaseLookup:
    def __init__(self, release: InstalledPluginRelease) -> None:
        self._release = release

    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None:
        release = self._release
        if (
            workspace_id == release.workspace_id
            and scope is release.scope
            and slug == release.slug
            and revision == release.revision
        ):
            return release
        return None

    async def get_selection(
        self,
        workspace_id: UUID,
        slug: str,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> None:
        del workspace_id, slug, scope
        return None

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> None:
        del workspace_id, slug, revision
        return None

    async def get_system_revocation(self, *, slug: str, revision: int) -> None:
        del slug, revision
        return None


def _unused_saved_graph_uow() -> Never:
    raise AssertionError("Admission parity test unexpectedly queried saved graphs")


def _contract(
    operator_id: str,
    *,
    capabilities: tuple[PluginRuntimeCapability, ...] = (),
) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id=operator_id,
        operator_version=1,
        title=operator_id,
        description="Admission parity fixture.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(
            PluginPortContract(
                name="text",
                title="Text",
                direction="output",
                artifact_type=TEXT_KEY,
                shape=PortShape.ONE,
                accepted_shapes=(PortShape.ONE,),
            ),
        ),
        required_capabilities=capabilities,
    )


def _release() -> InstalledPluginRelease:
    contracts = (
        _contract("parity.safe"),
        _contract(
            "parity.network",
            capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
        ),
    )
    catalog = PluginCatalogManifest(
        slug="parity",
        title="Parity",
        artifact_type_dependencies=(PluginArtifactTypeContract.from_spec(TEXT_VALUE),),
        nodes=contracts,
    )
    capabilities = PluginCapabilityManifest(
        capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)
    )
    runtime_artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/parity/runtime/r1.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/parity/r1.tar.gz",
        source_digest="d" * 64,
        lock_digest="e" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_user_id=WORKSPACE_ID,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=WORKSPACE_ID,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=WORKSPACE_ID,
            installed_by_platform_actor=None,
        ),
    )


def _compiler(
    tmp_path: Path,
    release: InstalledPluginRelease,
    admission: ReleaseExecutionAdmission,
) -> GraphCompiler:
    registry = PluginRegistry()
    context = PluginRuntimeContext(
        workspace=tmp_path,
        uploads_dir=tmp_path / "uploads",
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=InMemoryUnitOfWork(),
        bucket="artifacts",
    )
    return GraphCompiler(
        plugin_registry=registry,
        plugin_context=context,
        module_library=ModuleLibraryService(_unused_saved_graph_uow, registry),
        canonical_artifact_conversions=CANONICAL_ARTIFACT_CONVERSIONS_BY_KEY,
        plugin_release_lookup=_ReleaseLookup(release),
        plugin_invoker=_UnusedPluginInvoker(),
        release_admission=admission,
        build_digest="a" * 64,
    )


class _UnusedPluginInvoker:
    async def invoke(self, _request: object, /) -> Never:
        raise AssertionError("Admission parity test unexpectedly invoked a Plugin")


def _run_request(operator_id: str) -> RunRequest:
    return RunRequest(
        nodes=[
            RunNodeRequest(
                kind="plugin",
                id="node",
                operator_id=operator_id,
                operator_version=1,
                plugin_release=PluginReleasePinModel(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="parity",
                    revision=1,
                ),
            )
        ]
    )


@pytest.mark.asyncio
async def test_catalog_and_compiler_admit_each_contract_with_the_same_policy(
    tmp_path: Path,
) -> None:
    release = _release()
    admission = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
    )
    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            PluginRegistry(),
            [],
            [release],
            workspace_id=WORKSPACE_ID,
            release_admission=admission,
        ),
        _UnusedModuleExecutor(),
    )

    plugin = next(entry for entry in response.plugins if entry.slug == "parity")
    nodes = {node.operator_id: node for node in response.nodes}
    assert plugin.runnable is True
    assert nodes["parity.safe"].runnable is True
    assert nodes["parity.safe"].non_runnable_reason is None
    assert nodes["parity.network"].runnable is False
    assert nodes["parity.network"].non_runnable_reason == "unsupported_capabilities"

    compiled = await _compiler(tmp_path, release, admission).compile(
        _run_request("parity.safe"),
        _UnusedModuleExecutor(),
        workspace_id=WORKSPACE_ID,
    )
    assert compiled.nodes[0].request.operator_id == "parity.safe"
    with pytest.raises(GraphExecutionError, match="unsupported_capabilities"):
        await _compiler(tmp_path, release, admission).compile(
            _run_request("parity.network"),
            _UnusedModuleExecutor(),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("admission", "reason"),
    [
        (
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="missing-profile",
            ),
            "unsupported_runtime_profile",
        ),
        (
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
                supported_bundle_adapters=frozenset({("table-bundle", 1)}),
            ),
            "unsupported_artifact_type",
        ),
    ],
)
async def test_catalog_and_compiler_share_release_rejection_reasons(
    tmp_path: Path,
    admission: ReleaseExecutionAdmission,
    reason: str,
) -> None:
    release = _release()
    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            PluginRegistry(),
            [],
            [release],
            workspace_id=WORKSPACE_ID,
            release_admission=admission,
        ),
        _UnusedModuleExecutor(),
    )
    nodes = {
        node.operator_id: node
        for node in response.nodes
        if node.plugin_slug == "parity"
    }
    assert nodes["parity.safe"].non_runnable_reason == reason
    assert nodes["parity.network"].non_runnable_reason == "unsupported_capabilities"

    for operator_id in ("parity.safe", "parity.network"):
        expected_reason = (
            reason if operator_id == "parity.safe" else "unsupported_capabilities"
        )
        with pytest.raises(GraphExecutionError, match=expected_reason):
            await _compiler(tmp_path, release, admission).compile(
                _run_request(operator_id),
                _UnusedModuleExecutor(),
                workspace_id=WORKSPACE_ID,
            )
