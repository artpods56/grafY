from collections.abc import Sequence
from dataclasses import replace
from hashlib import sha256
from typing import Annotated, cast, get_args
from uuid import UUID

from pydantic import BaseModel, Field
import pytest

from grafy_core.application.plugin_releases import (
    require_canonical_conversion_references,
    require_workspace_catalog_authority,
)
from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactBundleFormat,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    NoConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.canonical_conversions import INTEGER_TO_TEXT
from grafy_core.domain.plugin_releases import (
    PLUGIN_CONTRACT_DIGEST_FIELD_ROLES,
    PluginArtifactBundleContract,
    PluginArtifactConversionContract,
    PluginArtifactConversionKey,
    PluginArtifactReferenceContract,
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginConfirmationRule,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginNodeHttpEgressContract,
    PluginPortContract,
    PluginRelease,
    PluginReleaseError,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    PluginSecretInputContract,
    plugin_contract_digest,
    plugin_contract_digest_matches,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_installations import PluginInstallation
from grafy_core.domain.plugin_identity import PluginReleaseNamespace
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import InPort, OutPort, PortShape
from grafy_core.artifact_contracts import (
    INTEGER_VALUE,
    RASTER_IMAGE,
    TEXT_VALUE,
    TextValue,
)
from grafy_core.prompt_contracts import PROMPT_MESSAGE
from grafy_workbench.arithmetic import ARITHMETIC
from grafy_workbench.table import TABLES
from grafy_workbench.text import TEXT
from grafy_core.plugins import Plugin
from tests.support.plugin_contract_digests import (
    stored_contract_digest_before_canonicalization,
)


PLUGIN = Plugin(slug="test.notes", title="Test notes")


class EchoInput(NodeInput):
    text: Annotated[TextValue, InPort(TEXT_VALUE), Field(description="Input text")]


class EchoOutput(NodeOutput):
    text: Annotated[TextValue, OutPort(TEXT_VALUE), Field(description="Output text")]


@PLUGIN.function_node(operator_id="test.notes.echo", version=1, title="Echo")
async def echo(_config: NoConfig, inputs: EchoInput) -> EchoOutput:
    return EchoOutput(text=inputs.text)


PORTABLE_VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("test.notes.portable_value", 1),
    title="Portable value",
    payload_schema={"type": "object"},
    materialized_json_type="string",
)


def _integer_to_portable_value(value: int) -> str:
    return str(value)


INTEGER_TO_PORTABLE_VALUE = ArtifactConversion(
    key=ArtifactConversionKey("test.notes.integer_to_portable_value", 1),
    source=ArtifactTypeKey("scalar.integer", 1),
    target=PORTABLE_VALUE.key,
    source_type=int,
    target_type=str,
    title="As portable value",
    convert=_integer_to_portable_value,
)


PLUGIN.register_artifact_type(PORTABLE_VALUE)
PLUGIN.register_artifact_type_dependency(INTEGER_VALUE)
PLUGIN.register_artifact_type_dependency(TEXT_VALUE)
PLUGIN.register_artifact_conversion(INTEGER_TO_PORTABLE_VALUE)


def _release(
) -> PluginRelease:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    capabilities = PluginCapabilityManifest()
    return PluginRelease(
        slug=catalog.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/test.notes/source.tar.gz",
        source_digest="4" * 64,
        lock_digest="5" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
    )


def test_catalog_manifest_is_derived_from_function_node_contracts() -> None:
    manifest = PluginCatalogManifest.from_plugin(PLUGIN)

    assert manifest.slug == "test.notes"
    assert len(manifest.nodes) == 1
    node = manifest.nodes[0]
    assert node.operator_id == "test.notes.echo"
    assert node.inputs[0].artifact_type is not None
    assert node.inputs[0].artifact_type.id == "scalar.text"
    assert node.outputs[0].artifact_type is not None
    assert node.outputs[0].artifact_type.id == "scalar.text"
    assert (
        PluginCatalogManifest.model_validate_json(manifest.model_dump_json())
        == manifest
    )


def test_catalog_manifest_serializes_portable_artifacts_and_exact_conversions() -> None:
    manifest = PluginCatalogManifest.from_plugin(PLUGIN)

    artifact = manifest.artifact_types[0]
    assert artifact.key == PluginArtifactTypeKey(
        id="test.notes.portable_value",
        schema_version=1,
    )
    assert artifact.materialized_json_type == "string"
    assert artifact.bundle == PluginArtifactBundleContract(
        format="inline-json",
        version=1,
    )
    assert manifest.artifact_conversions == (
        PluginArtifactConversionContract(
            key=PluginArtifactConversionKey(
                id="test.notes.integer_to_portable_value",
                version=1,
            ),
            source=PluginArtifactTypeKey(id="scalar.integer", schema_version=1),
            target=artifact.key,
            title="As portable value",
        ),
    )
    assert manifest.artifact_type_dependencies == (
        PluginArtifactTypeContract.from_spec(INTEGER_VALUE),
        PluginArtifactTypeContract.from_spec(TEXT_VALUE),
    )
    serialized = manifest.model_dump(mode="json")
    assert "source_type" not in serialized["artifact_conversions"][0]
    assert "target_type" not in serialized["artifact_conversions"][0]
    assert "convert" not in serialized["artifact_conversions"][0]

    round_tripped = PluginCatalogManifest.model_validate_json(
        manifest.model_dump_json()
    )
    assert round_tripped == manifest


def test_catalog_manifest_binds_inline_artifact_reference_contracts() -> None:
    prompt_contract = PluginArtifactTypeContract.from_spec(PROMPT_MESSAGE)
    assert prompt_contract.references == (
        PluginArtifactReferenceContract(
            path=("image_refs",),
            target=PluginArtifactTypeKey(id="image.raster", schema_version=1),
            shape="many",
        ),
    )

    manifest = PluginCatalogManifest.from_plugin(PLUGIN)
    payload = manifest.model_dump(mode="python")
    payload["artifact_type_dependencies"] = (
        *manifest.artifact_type_dependencies,
        prompt_contract,
    )
    with pytest.raises(ValueError, match="reference 'image_refs'.*neither owned"):
        PluginCatalogManifest.model_validate(payload)

    payload["artifact_type_dependencies"] = (
        *payload["artifact_type_dependencies"],
        PluginArtifactTypeContract.from_spec(RASTER_IMAGE),
    )
    validated = PluginCatalogManifest.model_validate(payload)
    assert validated.artifact_type_dependencies[-1].key == (
        PluginArtifactTypeKey(id="image.raster", schema_version=1)
    )


def test_catalog_manifest_requires_every_foreign_port_dependency() -> None:
    manifest = PluginCatalogManifest.from_plugin(PLUGIN)
    payload = manifest.model_copy(
        update={"artifact_type_dependencies": (manifest.artifact_type_dependencies[0],)}
    )

    with pytest.raises(ValueError, match="neither owned nor declared"):
        PluginCatalogManifest.model_validate(payload.model_dump())


def test_catalog_manifest_rejects_owned_dependency_overlap() -> None:
    manifest = PluginCatalogManifest.from_plugin(PLUGIN)
    payload = manifest.model_copy(
        update={
            "artifact_type_dependencies": (
                *manifest.artifact_type_dependencies,
                manifest.artifact_types[0],
            )
        }
    )

    with pytest.raises(ValueError, match="cannot both own and depend"):
        PluginCatalogManifest.model_validate(payload.model_dump())


def test_builtin_scalar_and_table_catalogs_preserve_portable_contracts() -> None:
    arithmetic = PluginCatalogManifest.from_plugin(ARITHMETIC)
    text = PluginCatalogManifest.from_plugin(TEXT)
    tables = PluginCatalogManifest.from_plugin(TABLES)

    integer_contract = next(
        artifact
        for artifact in arithmetic.artifact_types
        if artifact.key.id == "scalar.integer"
    )
    text_contract = next(
        artifact for artifact in text.artifact_types if artifact.key.id == "scalar.text"
    )
    table_contract = next(
        artifact
        for artifact in tables.artifact_types
        if artifact.key.id == "table.data"
    )

    assert integer_contract.materialized_json_type == "integer"
    assert integer_contract.bundle.format == "inline-json"
    assert text_contract.materialized_json_type == "string"
    assert text_contract.bundle.format == "inline-json"
    assert table_contract.bundle == PluginArtifactBundleContract(
        format="table-bundle",
        version=1,
    )
    assert text.artifact_conversions == ()


def test_artifact_and_conversion_contract_changes_are_digest_bound() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    artifact = catalog.artifact_types[0]
    conversion = catalog.artifact_conversions[0]
    changed_bundle = PluginCatalogManifest.model_validate(
        catalog.model_copy(
            update={
                "artifact_types": (
                    artifact.model_copy(
                        update={
                            "bundle": PluginArtifactBundleContract(
                                format="inline-json",
                                version=2,
                            )
                        }
                    ),
                )
            }
        ).model_dump()
    )
    changed_conversion = PluginCatalogManifest.model_validate(
        catalog.model_copy(
            update={
                "artifact_conversions": (
                    conversion.model_copy(update={"title": "Render portable value"}),
                )
            }
        ).model_dump()
    )
    changed_dependency = PluginCatalogManifest.model_validate(
        catalog.model_copy(
            update={
                "artifact_type_dependencies": (
                    catalog.artifact_type_dependencies[0].model_copy(
                        update={"title": "Different integer contract"}
                    ),
                    *catalog.artifact_type_dependencies[1:],
                )
            }
        ).model_dump()
    )

    assert plugin_contract_digest(changed_bundle) != plugin_contract_digest(catalog)
    assert plugin_contract_digest(changed_conversion) != plugin_contract_digest(catalog)
    assert plugin_contract_digest(changed_dependency) != plugin_contract_digest(catalog)


def test_catalog_manifest_rejects_conversion_identity_collisions() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    conversion = catalog.artifact_conversions[0]
    conflicting = conversion.model_copy(
        update={
            "target": PluginArtifactTypeKey(
                id="test.notes.different_target",
                schema_version=1,
            )
        }
    )
    payload = catalog.model_copy(
        update={"artifact_conversions": (conversion, conflicting)}
    )

    with pytest.raises(ValueError, match="unique identities"):
        PluginCatalogManifest.model_validate(payload.model_dump())


def test_catalog_manifest_leaves_conversion_authority_to_publication() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    conversion = catalog.artifact_conversions[0]
    payload = catalog.model_copy(
        update={
            "artifact_conversions": (
                conversion.model_copy(
                    update={
                        "key": PluginArtifactConversionKey(
                            id="other.integer_to_portable_value",
                            version=1,
                        )
                    }
                ),
            )
        }
    )

    validated = PluginCatalogManifest.model_validate(payload.model_dump())

    assert validated.artifact_conversions[0].key.id == (
        "other.integer_to_portable_value"
    )


def test_workspace_publication_accepts_only_exact_canonical_conversion_references(
) -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN).model_copy(
        update={
            "artifact_conversions": (
                PluginArtifactConversionContract.from_conversion(INTEGER_TO_TEXT),
            )
        }
    )

    require_workspace_catalog_authority(catalog)
    require_canonical_conversion_references(catalog)

    with pytest.raises(PluginReleaseError, match="deployment-owned canonical"):
        require_canonical_conversion_references(
            PluginCatalogManifest.from_plugin(PLUGIN)
        )


def test_artifact_bundle_contract_rejects_unknown_formats_and_versions() -> None:
    with pytest.raises(ValueError, match="Unsupported artifact bundle format"):
        ArtifactBundleContract(
            format=cast(ArtifactBundleFormat, "pickle"),
            version=1,
        )
    with pytest.raises(ValueError, match="version must be positive"):
        ArtifactBundleContract(format="inline-json", version=0)


def test_catalog_manifest_leaves_node_authority_to_publication() -> None:
    payload = PluginCatalogManifest.from_plugin(PLUGIN).model_dump(mode="json")
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    node = cast(dict[str, object], nodes[0])
    node["operator_id"] = "other.echo"

    validated = PluginCatalogManifest.model_validate(payload)

    assert validated.nodes[0].operator_id == "other.echo"


def test_catalog_manifest_leaves_artifact_authority_to_publication() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    replacement_key = PluginArtifactTypeKey(
        id="other.summary",
        schema_version=1,
    )
    payload = catalog.model_copy(
        update={
            "artifact_types": (
                PluginArtifactTypeContract(
                    key=replacement_key,
                    title="Summary",
                ),
            ),
            "artifact_conversions": (
                catalog.artifact_conversions[0].model_copy(
                    update={"target": replacement_key}
                ),
            ),
        }
    )

    validated = PluginCatalogManifest.model_validate(payload.model_dump())

    assert validated.artifact_types[0].key == replacement_key


def test_runtime_artifact_makes_release_executable_and_part_of_its_identity() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    capabilities = PluginCapabilityManifest()
    artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/test.notes/runtime/image.oci.tar",
        archive_digest="1" * 64,
        manifest_digest="2" * 64,
        config_digest="3" * 64,
    )
    source_only = PluginRelease(
        slug=catalog.slug,
        revision=1,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key="plugin-releases/test.notes/source.tar.gz",
        source_digest="4" * 64,
        lock_digest="5" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
    )
    executable = PluginRelease(
        slug=catalog.slug,
        revision=2,
        catalog=catalog,
        contract_digest=source_only.contract_digest,
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=source_only.protocol_digest,
        profile_digest=source_only.profile_digest,
        source_object_key=source_only.source_object_key,
        source_digest=source_only.source_digest,
        lock_digest=source_only.lock_digest,
        runtime_profile=source_only.runtime_profile,
        loader_target=source_only.loader_target,
        runtime_image_digest=artifact.manifest_digest,
        runtime_artifact=artifact,
    )

    assert source_only.executable is False
    assert executable.executable is True
    assert executable.descriptor.runtime_artifact == artifact
    assert executable.descriptor_digest != source_only.descriptor_digest


def test_release_rejects_runtime_image_that_does_not_match_oci_manifest() -> None:
    catalog = PluginCatalogManifest.from_plugin(PLUGIN)
    capabilities = PluginCapabilityManifest()
    artifact = PluginRuntimeArtifact(
        object_key="plugin-releases/test.notes/runtime/image.oci.tar",
        archive_digest="1" * 64,
        manifest_digest="2" * 64,
        config_digest="3" * 64,
    )

    with pytest.raises(PluginReleaseError, match="must match its OCI artifact"):
        PluginRelease(
            slug=catalog.slug,
            revision=1,
            catalog=catalog,
            contract_digest=plugin_contract_digest(catalog),
            capabilities=capabilities,
            capability_digest=capabilities.digest,
            protocol_digest=plugin_protocol_digest(),
            profile_digest=plugin_profile_digest("python-uv"),
            source_object_key="plugin-releases/test.notes/source.tar.gz",
            source_digest="4" * 64,
            lock_digest="5" * 64,
            runtime_profile="python-uv",
            loader_target="grafy_plugin:PLUGIN",
            runtime_image_digest="6" * 64,
            runtime_artifact=artifact,
        )


@pytest.mark.parametrize(
    "object_key",
    ["/absolute/image.oci.tar", "runtime/../image.oci.tar", r"runtime\image.oci.tar"],
)
def test_runtime_artifact_rejects_unsafe_object_keys(object_key: str) -> None:
    with pytest.raises(ValueError, match="object key must be safe"):
        PluginRuntimeArtifact(
            object_key=object_key,
            archive_digest="1" * 64,
            manifest_digest="2" * 64,
            config_digest="3" * 64,
        )


def test_installation_scope_requires_exactly_the_matching_workspace_owner() -> None:
    release = _release()
    with pytest.raises(ValueError, match="require a Workspace owner"):
        PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=None,
            ),
            execution_policy=PluginExecutionPolicy.ISOLATED_ONLY,
            installed_by_user_id=UUID(int=1),
            installed_by_platform_actor=None,
        )
    with pytest.raises(ValueError, match="cannot have a Workspace owner"):
        PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.SYSTEM,
                workspace_id=UUID(int=1),
            ),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            installed_by_user_id=None,
            installed_by_platform_actor="test:system",
        )
    with pytest.raises(PluginReleaseError, match="isolated-only"):
        PluginInstallation.from_release(
            release,
            namespace=PluginReleaseNamespace(
                scope=PluginReleaseScope.WORKSPACE,
                workspace_id=UUID(int=1),
            ),
            execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
            installed_by_user_id=UUID(int=1),
            installed_by_platform_actor=None,
        )

    system = PluginInstallation.from_release(
        release,
        namespace=PluginReleaseNamespace(
            scope=PluginReleaseScope.SYSTEM,
            workspace_id=None,
        ),
        execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
        installed_by_user_id=None,
        installed_by_platform_actor="test:system",
    )

    assert system.namespace.scope is PluginReleaseScope.SYSTEM
    assert system.namespace.storage_path == "system"
    assert system.execution_policy is PluginExecutionPolicy.HOST_ELIGIBLE


def test_untrusted_artifact_query_cannot_gain_network_secrets_or_native_access() -> None:
    with pytest.raises(ValueError, match="must require exactly sql.untrusted"):
        PluginNodeContract(
            operator_id="sql.artifacts.query",
            operator_version=1,
            title="Artifact query",
            description="Query authorized artifact tables",
            config_schema={"type": "object"},
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            inputs=(),
            outputs=(),
            required_capabilities=(
                PluginRuntimeCapability.NETWORK_EGRESS,
                PluginRuntimeCapability.UNTRUSTED_SQL,
            ),
        )


def test_release_capabilities_are_normalized_and_equal_exact_node_union() -> None:
    normalized = PluginCapabilityManifest(
        capabilities=(
            PluginRuntimeCapability.NETWORK_EGRESS,
            PluginRuntimeCapability.NETWORK_EGRESS,
        )
    )
    assert normalized.capabilities == (PluginRuntimeCapability.NETWORK_EGRESS,)
    node = PluginNodeContract(
        operator_id="test.notes.network",
        operator_version=1,
        title="Network",
        description="Use one exact network capability.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(),
        required_capabilities=(
            PluginRuntimeCapability.NETWORK_EGRESS,
            PluginRuntimeCapability.NETWORK_EGRESS,
        ),
    )
    assert node.required_capabilities == (PluginRuntimeCapability.NETWORK_EGRESS,)

    release = _release()
    with pytest.raises(PluginReleaseError, match="exceeds exact node requirements"):
        replace(
            release,
            capabilities=normalized,
            capability_digest=normalized.digest,
            descriptor_digest=None,
        )


def _http_egress_node(
    *,
    http_egress: object | None = None,
    capabilities: tuple[PluginRuntimeCapability, ...] = (),
) -> PluginNodeContract:
    return PluginNodeContract(
        operator_id="test.notes.network",
        operator_version=1,
        title="Network",
        description="One node that may request HTTP egress.",
        config_schema={"type": "object"},
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        inputs=(),
        outputs=(),
        required_capabilities=capabilities,
        http_egress=http_egress,
    )


def _catalog_with(node: PluginNodeContract) -> PluginCatalogManifest:
    return PluginCatalogManifest(
        slug="test.notes",
        title="Test notes",
        nodes=(node,),
    )


def test_node_http_egress_contract_validates_declared_fields() -> None:
    from grafy_core.domain.plugin_releases import PluginNodeHttpEgressContract

    contract = PluginNodeHttpEgressContract(configured_inputs=("base_url",))
    assert contract.configured_inputs == ("base_url",)
    assert contract.dynamic_destinations is False

    with pytest.raises(ValueError, match="must be unique"):
        PluginNodeHttpEgressContract(
            configured_inputs=("base_url", "base_url")
        )

    with pytest.raises(ValueError, match="more than eight"):
        PluginNodeHttpEgressContract(
            configured_inputs=tuple(f"url_{index}" for index in range(9))
        )

    with pytest.raises(ValueError, match="config field names"):
        PluginNodeHttpEgressContract(configured_inputs=("Base-URL",))


def test_plugin_node_contract_http_egress_requires_network_egress() -> None:
    from grafy_core.domain.plugin_releases import PluginNodeHttpEgressContract

    with pytest.raises(ValueError, match="requires network.egress"):
        _http_egress_node(
            http_egress=PluginNodeHttpEgressContract(configured_inputs=("base_url",))
        )

    historical = _http_egress_node(
        capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)
    )
    assert historical.http_egress is None


def test_contract_digest_stays_stable_for_catalogs_without_http_egress() -> None:
    node = _http_egress_node(
        capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)
    )
    catalog = _catalog_with(node)
    serialized = catalog.model_dump_json()
    assert ',"http_egress":null' in serialized

    legacy_bytes = serialized.replace(',"http_egress":null', "").encode("utf-8")
    assert plugin_contract_digest(catalog) == sha256(legacy_bytes).hexdigest()


def test_contract_digest_changes_when_http_egress_is_declared() -> None:
    from grafy_core.domain.plugin_releases import PluginNodeHttpEgressContract

    baseline = plugin_contract_digest(
        _catalog_with(
            _http_egress_node(
                capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)
            )
        )
    )
    declared = plugin_contract_digest(
        _catalog_with(
            _http_egress_node(
                capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
                http_egress=PluginNodeHttpEgressContract(
                    configured_inputs=("base_url",)
                ),
            )
        )
    )
    assert declared != baseline


def test_catalog_manifest_round_trips_the_http_egress_contract() -> None:
    from grafy_core.domain.plugin_releases import PluginNodeHttpEgressContract

    catalog = _catalog_with(
        _http_egress_node(
            capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,),
            http_egress=PluginNodeHttpEgressContract(
                configured_inputs=("base_url", "fallback_url"),
                dynamic_destinations=True,
            ),
        )
    )

    restored = PluginCatalogManifest.model_validate_json(catalog.model_dump_json())
    assert restored.nodes[0].http_egress == PluginNodeHttpEgressContract(
        configured_inputs=("base_url", "fallback_url"),
        dynamic_destinations=True,
    )


_CATALOG_BYTES_BEFORE_EXTENSION_CONTRACT = (
    ',"http_egress":null',
    ',"also_accepts":[]',
    ',"extensions":[]',
    ',"confirmation_rule":{"rule":"none","signatures":[]}',
)


def _contract_catalog(
    *,
    extensions: tuple[str, ...] = (),
    confirmation_rule: PluginConfirmationRule = PluginConfirmationRule(),
) -> PluginCatalogManifest:
    """Catalog that instantiates every contract model with defaulted fields.

    The second node carries a declared HTTP egress contract and a secret input,
    so ``PluginNodeHttpEgressContract`` and ``PluginSecretInputContract`` are
    part of the hashed bytes. Without them a new empty default classified
    ``keep`` on either model would leave the pinned digest green.
    """

    key = PluginArtifactTypeKey(id="file.png", schema_version=1)
    port = PluginPortContract(
        name="file",
        direction="input",
        artifact_type=key,
        shape=PortShape.ONE,
        accepted_shapes=(PortShape.ONE,),
    )
    return PluginCatalogManifest(
        slug="test.notes",
        title="Test notes",
        artifact_types=(
            PluginArtifactTypeContract(
                key=key,
                title="PNG file",
                extensions=extensions,
                confirmation_rule=confirmation_rule,
            ),
        ),
        nodes=(
            PluginNodeContract(
                operator_id="test.notes.echo",
                operator_version=1,
                title="Echo",
                description="Echo one file.",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(port,),
                outputs=(),
            ),
            PluginNodeContract(
                operator_id="test.notes.fetch",
                operator_version=1,
                title="Fetch",
                description="Fetch one URL.",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(port,),
                outputs=(),
                secret_inputs=(
                    PluginSecretInputContract(name="api_key", title="API key"),
                ),
                required_capabilities=(
                    PluginRuntimeCapability.NETWORK_EGRESS,
                    PluginRuntimeCapability.NODE_SECRETS,
                ),
                http_egress=PluginNodeHttpEgressContract(),
            ),
        ),
    )


def test_contract_digest_stays_stable_for_catalogs_without_extension_defaults() -> (
    None
):
    catalog = _contract_catalog()
    serialized = catalog.model_dump_json()
    for fragment in _CATALOG_BYTES_BEFORE_EXTENSION_CONTRACT:
        assert fragment in serialized

    before_extension_contract = serialized
    for fragment in _CATALOG_BYTES_BEFORE_EXTENSION_CONTRACT:
        before_extension_contract = before_extension_contract.replace(fragment, "")
    assert plugin_contract_digest(catalog) == sha256(
        before_extension_contract.encode("utf-8")
    ).hexdigest()


def test_contract_digest_changes_when_an_extension_claim_is_declared() -> None:
    assert plugin_contract_digest(
        _contract_catalog(extensions=("png",))
    ) != plugin_contract_digest(_contract_catalog())


def test_contract_digest_changes_when_a_confirmation_rule_is_declared() -> None:
    assert plugin_contract_digest(
        _contract_catalog(
            confirmation_rule=PluginConfirmationRule(rule="json_document")
        )
    ) != plugin_contract_digest(_contract_catalog())


def _catalog_contract_instances(catalog: BaseModel) -> set[type[BaseModel]]:
    """Every Pydantic model instantiated inside a catalog contract."""

    instances: set[type[BaseModel]] = set()
    pending: list[object] = [catalog]
    while pending:
        value = pending.pop()
        if isinstance(value, BaseModel):
            instances.add(type(value))
            pending.extend(getattr(value, name) for name in type(value).model_fields)
        elif isinstance(value, (tuple, list)):
            pending.extend(cast(Sequence[object], value))
        elif isinstance(value, dict):
            pending.extend(cast(dict[str, object], value).values())
    return instances


def test_contract_digest_ignores_every_empty_defaulting_catalog_field() -> None:
    """Pin the digest of the catalog whose defaulted fields are all empty.

    A new defaulted field keeps this value only while it is classified
    ``omit``: a ``keep`` classification re-hashes the default and breaks the
    bytes persisted before the field existed. Recompute this literal only
    after deciding that role.
    """

    catalog = _contract_catalog()
    assert plugin_contract_digest(catalog) == (
        "4531883a81e55e8bcce716b48d31e62b096d7e8b43993f50bbf0f16dbc80b377"
    )
    # A model the pinned catalog never instantiates cannot fail the pin, so a
    # new empty default classified ``keep`` on it would stay green while every
    # row persisted before that field failed verification.
    assert _catalog_contract_instances(catalog) >= set(
        PLUGIN_CONTRACT_DIGEST_FIELD_ROLES
    )


def test_contract_digest_accepts_releases_persisted_before_canonicalization() -> None:
    catalog = _contract_catalog()
    stored = stored_contract_digest_before_canonicalization(catalog)
    assert stored != plugin_contract_digest(catalog)

    assert plugin_contract_digest_matches(catalog, plugin_contract_digest(catalog))
    assert plugin_contract_digest_matches(catalog, stored)
    assert not plugin_contract_digest_matches(catalog, "0" * 64)

    capabilities = PluginCapabilityManifest(
        capabilities=(
            PluginRuntimeCapability.NETWORK_EGRESS,
            PluginRuntimeCapability.NODE_SECRETS,
        )
    )
    release = replace(
        _release(),
        catalog=catalog,
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        contract_digest=stored,
        descriptor_digest=None,
    )
    assert release.contract_digest == stored


def _catalog_contract_models() -> set[type[BaseModel]]:
    """Every Pydantic model reachable inside the catalog contract."""

    models: set[type[BaseModel]] = set()
    pending: list[object] = [PluginCatalogManifest]
    while pending:
        annotation = pending.pop()
        arguments = get_args(annotation)
        if arguments:
            pending.extend(arguments)
        elif (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and annotation not in models
        ):
            models.add(annotation)
            pending.extend(
                field.annotation for field in annotation.model_fields.values()
            )
    return models


def test_contract_digest_classifies_every_defaulted_catalog_field() -> None:
    classified = {
        (model.__name__, name)
        for model, roles in PLUGIN_CONTRACT_DIGEST_FIELD_ROLES.items()
        for name in roles
    }
    observed = {
        (model.__name__, name)
        for model in _catalog_contract_models()
        for name, field in model.model_fields.items()
        if not field.is_required()
    }
    assert classified == observed
