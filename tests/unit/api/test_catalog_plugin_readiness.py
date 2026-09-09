from collections.abc import Mapping
from hashlib import sha256
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_core.domain.plugin_releases import (
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginNodeContract,
    PluginPortContract,
    PluginPortDirection,
    PluginRelease,
    PluginExecutionPolicy,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    PluginSecretInputContract,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationReason,
)
from grafy_core.domain.plugin_selection import (
    PluginFamilyLifecycle,
    PluginReleaseSelection,
)
from grafy_core.artifacts import ArtifactRef, NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.module_library import Module, ModuleRelease
from grafy_core.domain.modules import GraphModuleDefinition, GraphModuleReference
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphDocument,
    SavedGraphNode,
    SavedGraphEdge,
    SavedGraphArtifactTypeBinding,
)
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.operators.modules import MODULE_BOUNDARY_REGISTRATIONS
from grafy_workbench.arithmetic import ARITHMETIC
from grafy_core.artifact_contracts import RASTER_IMAGE, TEXT_VALUE
from grafy_core.table_contracts import TABLE_DATA
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_workbench import BuiltinNodeCatalog
from grafy_workbench.text import TEXT
from grafy_core.plugins import Plugin, PluginRegistry
from grafy_core.ports.modules import GraphModuleExecutionResult

from grafy_api.catalog import CatalogSnapshot
from grafy_api.plugins.runtime.admission import (
    ReleaseExecutionAdmission,
    ReleaseExecutionRoute,
)
from grafy_api.v1.routes.catalog.models import (
    NodeRegistryResponse,
    PluginNonRunnableReason,
    PluginSpecResponse,
)
from grafy_api.catalog import PluginCatalogReleaseState, plugin_release_readiness


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000661")
OTHER_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000662")


class NotesConfig(NodeConfig):
    pass


class NotesInput(NodeInput):
    pass


class NotesOutput(NodeOutput):
    pass


HOST_NOTES = Plugin(slug="notes", title="Host notes")


@HOST_NOTES.function_node(
    operator_id="notes.transform",
    version=1,
    title="Host transform",
)
async def host_notes_transform(
    config: NotesConfig,
    inputs: NotesInput,
) -> NotesOutput:
    del config, inputs
    return NotesOutput()


class UnusedModuleExecutor:
    async def execute_module(
        self,
        definition: GraphModuleDefinition,
        context: NodeExecutionContext,
        inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        raise AssertionError(
            f"Unexpected module execution for {definition.reference} with "
            f"{len(inputs)} inputs in {context}"
        )


def _port(
    name: str,
    direction: PluginPortDirection,
    artifact_type: str,
) -> PluginPortContract:
    return PluginPortContract(
        name=name,
        direction=direction,
        artifact_type=PluginArtifactTypeKey(
            id=artifact_type,
            schema_version=1,
        ),
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
    )


def _release(
    *,
    workspace_id: UUID = WORKSPACE_ID,
    executable: bool = True,
    protocol_digest: str | None = None,
    runtime_profile: str = "python-uv",
    capabilities: tuple[PluginRuntimeCapability, ...] = (),
    input_type: str = "table.data",
    output_type: str = "scalar.text",
    own_output_type: bool = False,
    secret_inputs: bool = False,
) -> InstalledPluginRelease:
    if secret_inputs and PluginRuntimeCapability.NODE_SECRETS not in capabilities:
        capabilities = (*capabilities, PluginRuntimeCapability.NODE_SECRETS)
    artifact_types = (
        (
            PluginArtifactTypeContract(
                key=PluginArtifactTypeKey(id=output_type, schema_version=1),
                title="Owned output",
                payload_schema={"type": "object"},
            ),
        )
        if own_output_type
        else ()
    )
    artifact_type_dependencies = [
        PluginArtifactTypeContract.from_spec(spec)
        for spec in (TABLE_DATA, TEXT_VALUE, RASTER_IMAGE, JSON_SCHEMA)
        if spec.key.id in {input_type, output_type}
    ]
    if input_type == "other.private_type":
        artifact_type_dependencies.append(
            PluginArtifactTypeContract(
                key=PluginArtifactTypeKey(
                    id="other.private_type",
                    schema_version=1,
                ),
                title="Cross-Plugin private type",
            )
        )
    catalog = PluginCatalogManifest(
        slug="notes",
        title="Notes",
        artifact_types=artifact_types,
        artifact_type_dependencies=tuple(artifact_type_dependencies),
        nodes=(
            PluginNodeContract(
                operator_id="notes.transform",
                operator_version=1,
                title="Transform",
                description="Transform one artifact",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(_port("source", "input", input_type),),
                outputs=(_port("result", "output", output_type),),
                secret_inputs=(
                    (
                        PluginSecretInputContract(
                            name="token",
                            title="Token",
                        ),
                    )
                    if secret_inputs
                    else ()
                ),
                required_capabilities=tuple(
                    sorted(set(capabilities), key=lambda capability: capability.value)
                ),
            ),
        ),
    )
    declared_capabilities = set(capabilities)
    if secret_inputs:
        declared_capabilities.add(PluginRuntimeCapability.NODE_SECRETS)
    capability_manifest = PluginCapabilityManifest(
        capabilities=tuple(declared_capabilities)
    )
    runtime_artifact = (
        PluginRuntimeArtifact(
            object_key="plugin-releases/notes/runtime/image.oci.tar",
            archive_digest="1" * 64,
            manifest_digest="2" * 64,
            config_digest="3" * 64,
        )
        if executable
        else None
    )
    release = PluginRelease(
        slug="notes",
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capability_manifest,
        capability_digest=capability_manifest.digest,
        protocol_digest=protocol_digest or plugin_protocol_digest(),
        profile_digest=plugin_profile_digest(runtime_profile),
        source_object_key="plugin-releases/notes/source.tar.gz",
        source_digest="4" * 64,
        lock_digest="5" * 64,
        runtime_profile=runtime_profile,
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=(
            runtime_artifact.manifest_digest if runtime_artifact is not None else None
        ),
        runtime_artifact=runtime_artifact,
        published_by_user_id=workspace_id,
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=workspace_id,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=workspace_id,
            installed_by_platform_actor=None,
        ),
    )


def _system_release(
    plugin: Plugin,
    *,
    catalog: PluginCatalogManifest | None = None,
) -> InstalledPluginRelease:
    catalog = catalog or PluginCatalogManifest.from_plugin(plugin)
    capabilities = PluginCapabilityManifest(capabilities=plugin.capabilities)
    runtime_artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/system/notes/runtime/image.oci.tar",
        archive_digest="6" * 64,
        manifest_digest="7" * 64,
        config_digest="8" * 64,
    )
    release = PluginRelease(
        slug=catalog.slug,
        revision=3,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/system/notes/source.tar.gz",
        source_digest="9" * 64,
        lock_digest="a" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor="test:system-catalog",
    )
    return InstalledPluginRelease(
        release=release,
        installation=PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=None,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=None,
            installed_by_platform_actor="test:system-catalog",
        ),
    )


def _system_notes_release() -> InstalledPluginRelease:
    return _system_release(HOST_NOTES)


@pytest.mark.parametrize(
    ("release", "admission", "reason"),
    [
        (
            _release(executable=False),
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
            "missing_runtime_artifact",
        ),
        (
            _release(protocol_digest=sha256(b"grafy-plugin-invocation@1").hexdigest()),
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
            "incompatible_protocol",
        ),
        (
            _release(runtime_profile="python-uv-gdal"),
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
            "unsupported_runtime_profile",
        ),
        (
            _release(capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)),
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
            "unsupported_capabilities",
        ),
        (
            _release(secret_inputs=True),
            ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
            "unsupported_capabilities",
        ),
        (
            _release(),
            ReleaseExecutionAdmission(
                isolated_adapter_available=False,
                runtime_profile="python-uv",
            ),
            "plugin_runtime_unavailable",
        ),
    ],
)
def test_release_readiness_returns_a_stable_fail_closed_reason(
    release: InstalledPluginRelease,
    admission: ReleaseExecutionAdmission,
    reason: PluginNonRunnableReason,
) -> None:
    readiness = plugin_release_readiness(release, admission)

    assert readiness.runnable is False
    assert readiness.reason == reason
    assert readiness.detail


def test_release_readiness_accepts_table_core_scalars_and_owned_inline_types() -> None:
    release = _release(
        output_type="notes.table_summary",
        own_output_type=True,
    )

    readiness = plugin_release_readiness(
        release,
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
        ),
    )

    assert readiness.runnable is True
    assert readiness.reason is None
    assert readiness.detail is None

    decision = ReleaseExecutionAdmission(
        isolated_adapter_available=True,
        runtime_profile="python-uv",
    ).decide(release)
    assert decision is ReleaseExecutionRoute.ISOLATED


def test_release_admission_accepts_exact_serialized_foreign_dependencies() -> None:
    release = _release(input_type="other.private_type")

    readiness = plugin_release_readiness(
        release,
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
        ),
    )

    assert readiness.runnable is True
    assert readiness.reason is None


@pytest.mark.parametrize(
    "lifecycle",
    [PluginFamilyLifecycle.DEPRECATED, PluginFamilyLifecycle.WITHDRAWN],
)
def test_release_readiness_disables_non_published_families_for_new_insertion(
    lifecycle: PluginFamilyLifecycle,
) -> None:
    release = _release()
    selection = PluginReleaseSelection.from_release(release)
    selection.lifecycle = lifecycle

    readiness = plugin_release_readiness(
        release,
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
        ),
        state=PluginCatalogReleaseState(selection=selection),
    )

    assert readiness.runnable is False
    assert readiness.reason == lifecycle.value
    assert readiness.detail is not None
    assert "new insertion" in readiness.detail


def test_release_readiness_prioritizes_exact_revocation_over_family_lifecycle() -> None:
    release = _release()
    selection = PluginReleaseSelection.from_release(release)
    selection.lifecycle = PluginFamilyLifecycle.WITHDRAWN
    revocation = PluginReleaseRevocation.from_release(
        release,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=UUID("00000000-0000-4000-8000-000000000663"),
    )

    readiness = plugin_release_readiness(
        release,
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
        ),
        state=PluginCatalogReleaseState(
            selection=selection,
            revocation=revocation,
        ),
    )

    assert readiness.runnable is False
    assert readiness.reason == "revoked"
    assert readiness.detail is not None


def test_exact_foreign_dependency_makes_cross_plugin_type_portable() -> None:
    release = _release(
        input_type="other.private_type",
        output_type="notes.table_summary",
        own_output_type=True,
    )

    readiness = plugin_release_readiness(
        release,
        ReleaseExecutionAdmission(
            isolated_adapter_available=True,
            runtime_profile="python-uv",
        ),
    )

    assert readiness.runnable is True
    assert readiness.reason is None
    assert readiness.detail is None


def test_system_release_presents_published_plugin_nodes_with_an_exact_pin() -> None:
    registry = PluginRegistry()
    release = _system_notes_release()

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            registry,
            [],
            [release],
            workspace_id=WORKSPACE_ID,
            release_admission=ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
        ),
        UnusedModuleExecutor(),
    )

    notes_plugins = [
        plugin for plugin in response.plugins if plugin.slug == release.release.slug
    ]
    assert len(notes_plugins) == 1
    plugin = notes_plugins[0]
    assert plugin.origin == "plugin"
    assert plugin.entry_kind == "plugin"
    assert plugin.scope is PluginReleaseScope.SYSTEM
    assert plugin.installation_scope is PluginReleaseScope.SYSTEM
    assert plugin.plugin_release is not None
    assert plugin.plugin_release.scope is PluginReleaseScope.SYSTEM
    assert plugin.plugin_release.slug == release.release.slug
    assert plugin.plugin_release.revision == release.release.revision
    assert plugin.revision == release.release.revision

    notes_nodes = [
        node for node in response.nodes if node.plugin_slug == release.release.slug
    ]
    assert len(notes_nodes) == len(release.release.catalog.nodes)
    assert all(node.plugin_release is not None for node in notes_nodes)
    assert all(
        node.plugin_release.scope is PluginReleaseScope.SYSTEM
        for node in notes_nodes
        if node.plugin_release is not None
    )


def test_system_release_rejects_a_different_host_node_contract() -> None:
    registry = PluginRegistry()
    registry.install(HOST_NOTES)
    catalog = PluginCatalogManifest.from_plugin(HOST_NOTES)
    changed_node = catalog.nodes[0].model_copy(update={"title": "Changed"})
    changed_catalog = catalog.model_copy(update={"nodes": (changed_node,)})

    with pytest.raises(ValueError, match="reserved builtin families"):
        NodeRegistryResponse.from_snapshot(
            CatalogSnapshot.from_registry(
                registry,
                [],
                [_system_release(HOST_NOTES, catalog=changed_catalog)],
                workspace_id=WORKSPACE_ID,
            ),
            UnusedModuleExecutor(),
        )


def test_builtin_registry_families_appear_in_catalog_without_releases() -> None:
    registry = PluginRegistry()
    registry.install(HOST_NOTES)

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(registry, [], [], workspace_id=WORKSPACE_ID),
        UnusedModuleExecutor(),
    )

    notes = next(entry for entry in response.plugins if entry.slug == "notes")
    assert notes.origin == "builtin"
    assert notes.plugin_release is None
    assert {node.operator_id for node in response.nodes} == {"notes.transform"}
    assert all(node.origin == "builtin" for node in response.nodes)


def test_catalog_keeps_withdrawn_release_visible_disabled_and_exactly_pinned() -> None:
    release = _release()
    selection = PluginReleaseSelection.from_release(release)
    selection.lifecycle = PluginFamilyLifecycle.WITHDRAWN

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            PluginRegistry(),
            [],
            [release],
            workspace_id=WORKSPACE_ID,
            release_admission=ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
            plugin_release_states={
                release.release.id: PluginCatalogReleaseState(selection=selection)
            },
        ),
        UnusedModuleExecutor(),
    )

    plugin = next(
        entry for entry in response.plugins if entry.slug == release.release.slug
    )
    node = next(
        entry for entry in response.nodes if entry.plugin_slug == release.release.slug
    )
    assert plugin.runnable is False
    assert plugin.non_runnable_reason == "withdrawn"
    assert plugin.plugin_release is not None
    assert plugin.plugin_release.revision == release.release.revision
    assert node.runnable is False
    assert node.non_runnable_reason == "withdrawn"
    assert node.plugin_release is not None
    assert node.plugin_release.revision == release.release.revision


def test_builtin_catalog_exposes_host_artifact_and_conversion_contracts() -> None:
    registry = PluginRegistry()
    registry.install(ARITHMETIC)
    registry.install(TEXT)
    registry.freeze()

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(registry, [], [], workspace_id=WORKSPACE_ID),
        UnusedModuleExecutor(),
    )

    artifact_keys = [
        (artifact.key.id, artifact.key.schema_version)
        for artifact in response.artifact_types
    ]
    conversion_keys = [
        (conversion.key.id, conversion.key.version)
        for conversion in response.artifact_conversions
    ]
    assert len(artifact_keys) == len(set(artifact_keys))
    assert conversion_keys == [("builtin.scalar.integer_to_text", 1)]
    assert ("scalar.integer", 1) in artifact_keys
    assert ("scalar.text", 1) in artifact_keys


def test_system_release_accepts_exact_installed_foreign_artifact_dependency() -> None:
    registry = PluginRegistry()
    registry.install(ARITHMETIC)
    registry.install(TEXT)
    registry.freeze()
    release = _system_release(HOST_NOTES)

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            registry,
            [],
            [release],
            workspace_id=WORKSPACE_ID,
            release_admission=ReleaseExecutionAdmission(
                isolated_adapter_available=True,
                runtime_profile="python-uv",
            ),
        ),
        UnusedModuleExecutor(),
    )

    response_keys = {
        (artifact.key.id, artifact.key.schema_version)
        for artifact in response.artifact_types
    }
    assert ("scalar.integer", 1) in response_keys
    assert ("scalar.text", 1) in response_keys


def test_plugin_dependency_on_host_artifact_keeps_expanded_host_contract() -> None:
    registry = BuiltinNodeCatalog.load("a" * 64).registry

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(
            registry,
            [],
            [_release(input_type="json.schema", output_type="json.schema")],
            workspace_id=WORKSPACE_ID,
        ),
        UnusedModuleExecutor(),
    )

    schema = next(
        artifact
        for artifact in response.artifact_types
        if artifact.key.id == "json.schema"
    )
    assert schema.field_projections
    assert {plugin.slug for plugin in response.plugins} >= {
        "graph.module",
        "schema",
        "notes",
    }


def test_system_release_rejects_same_key_with_different_host_artifact_contract() -> (
    None
):
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()
    catalog = PluginCatalogManifest.from_plugin(HOST_NOTES)
    changed_artifact = PluginArtifactTypeContract.from_spec(TEXT_VALUE).model_copy(
        update={"title": "Changed host contract"}
    )
    changed_catalog = catalog.model_copy(
        update={"artifact_types": (changed_artifact,)},
    )

    with pytest.raises(ValueError, match="conflicts with the host catalog contract"):
        NodeRegistryResponse.from_snapshot(
            CatalogSnapshot.from_registry(
                registry,
                [],
                [_system_release(HOST_NOTES, catalog=changed_catalog)],
                workspace_id=WORKSPACE_ID,
            ),
            UnusedModuleExecutor(),
        )


def test_builtin_catalog_entries_do_not_use_plugin_releases() -> None:
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()

    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(registry, [], [], workspace_id=WORKSPACE_ID),
        UnusedModuleExecutor(),
    )

    text = next(plugin for plugin in response.plugins if plugin.slug == "text")
    assert text.origin == "builtin"
    assert text.plugin_release is None
    assert text.scope is None
    nodes = [node for node in response.nodes if node.plugin_slug == "text"]
    assert nodes
    assert all(node.origin == "builtin" for node in nodes)
    assert all(node.plugin_release is None for node in nodes)


def test_published_plugin_cannot_override_a_reserved_builtin_operator() -> None:
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.freeze()

    with pytest.raises(ValueError, match="reserved builtin families"):
        NodeRegistryResponse.from_snapshot(
            CatalogSnapshot.from_registry(
                registry, [], [_system_release(TEXT)], workspace_id=WORKSPACE_ID
            ),
            UnusedModuleExecutor(),
        )


def test_module_provider_is_a_separate_entry_kind_without_plugin_scope() -> None:
    registry = PluginRegistry()
    registry.register_module_boundaries(MODULE_BOUNDARY_REGISTRATIONS)
    response = NodeRegistryResponse.from_snapshot(
        CatalogSnapshot.from_registry(registry, [], [], workspace_id=WORKSPACE_ID),
        UnusedModuleExecutor(),
    )

    module = next(
        plugin for plugin in response.plugins if plugin.slug == "graph.module"
    )
    assert module.origin == "module"
    assert module.entry_kind == "module"
    assert module.scope is None
    assert module.plugin_release is None
    assert {node.operator_id for node in response.nodes} == {
        "module.input",
        "module.output",
    }
    assert {node.plugin_slug for node in response.nodes} == {"graph.module"}


def test_plugin_catalog_entry_requires_an_exact_release() -> None:
    with pytest.raises(ValidationError, match="must declare an exact release"):
        PluginSpecResponse(
            slug="notes",
            title="Notes",
            scope=PluginReleaseScope.WORKSPACE,
        )


def test_catalog_rejects_a_foreign_workspace_release() -> None:
    with pytest.raises(ValueError, match="foreign releases.*notes@1"):
        NodeRegistryResponse.from_snapshot(
            CatalogSnapshot.from_registry(
                PluginRegistry(),
                [],
                [_release(workspace_id=OTHER_WORKSPACE_ID)],
                workspace_id=WORKSPACE_ID,
            ),
            UnusedModuleExecutor(),
        )


def test_catalog_rejects_a_system_workspace_slug_collision() -> None:
    system_release = _system_notes_release()
    workspace_release = _release()

    with pytest.raises(
        ValueError,
        match="Workspace Plugin releases conflict with System Plugins: notes",
    ):
        NodeRegistryResponse.from_snapshot(
            CatalogSnapshot.from_registry(
                PluginRegistry(),
                [],
                [system_release, workspace_release],
                workspace_id=WORKSPACE_ID,
            ),
            UnusedModuleExecutor(),
        )


@pytest.mark.parametrize(
    "scope", [PluginReleaseScope.SYSTEM, PluginReleaseScope.WORKSPACE]
)
def test_snapshot_rejects_duplicate_selected_families(
    scope: PluginReleaseScope,
) -> None:
    release = (
        _system_notes_release() if scope is PluginReleaseScope.SYSTEM else _release()
    )
    with pytest.raises(ValueError, match="duplicate current slugs"):
        CatalogSnapshot.from_registry(
            PluginRegistry(),
            [],
            [release, release],
            workspace_id=WORKSPACE_ID,
        )


def test_snapshot_rejects_duplicate_module_identity_without_an_executor() -> None:
    graph_id = UUID(int=16)
    module = Module(workspace_id=WORKSPACE_ID, source_graph_id=graph_id, name="Module")
    release = ModuleRelease(
        workspace_id=WORKSPACE_ID,
        module_id=module.id,
        revision=1,
        source_graph_id=graph_id,
    )
    definition = GraphModuleDefinition(
        reference=GraphModuleReference(graph_id=graph_id, revision=1),
        name="Module",
        document=SavedGraphDocument(
            nodes=tuple(
                SavedGraphNode(
                    kind="module",
                    id=node_id,
                    operator_id=f"module.{node_id}",
                    operator_version=1,
                    config={"public_name": "text"},
                    position=GraphPoint(x=0, y=0),
                    artifact_type_bindings=(
                        SavedGraphArtifactTypeBinding(
                            variable="T",
                            artifact_type=TEXT_VALUE.key,
                        ),
                    ),
                )
                for node_id in ("input", "output")
            ),
            edges=(
                SavedGraphEdge(
                    id="edge",
                    from_node="input",
                    from_port="value",
                    to_node="output",
                    to_port="value",
                ),
            ),
        ),
    )
    entry = (module, release, definition)
    with pytest.raises(ValueError, match="conflicts with another catalog entry"):
        CatalogSnapshot.from_registry(
            PluginRegistry(),
            [entry, entry],
            [],
            workspace_id=WORKSPACE_ID,
        )
