from collections.abc import Sequence
from typing import Annotated, cast, get_args

from pydantic import BaseModel, Field
import pytest

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
from grafy_core.domain.plugin_releases import (
    PluginArtifactBundleContract,
    PluginArtifactConversionContract,
    PluginArtifactConversionKey,
    PluginArtifactReferenceContract,
    PluginArtifactTypeContract,
    PluginArtifactTypeKey,
    PluginCatalogManifest,
    PluginConfirmationRule,
    PluginNodeContract,
    PluginNodeHttpEgressContract,
    PluginPortContract,
    PluginSecretInputContract,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import InPort, OutPort, PortShape
from grafy_core.artifact_contracts import (
    INTEGER_VALUE,
    RASTER_IMAGE,
    TEXT_VALUE,
    TextValue,
)
from grafy_core.prompt_contracts import PROMPT_MESSAGE
from grafy_workbench.value import VALUE
from grafy_workbench.table import TABLES
from grafy_workbench.text import TEXT
from grafy_core.plugins import Plugin


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
    value = PluginCatalogManifest.from_plugin(VALUE)
    text = PluginCatalogManifest.from_plugin(TEXT)
    table_contracts = tuple(
        PluginArtifactTypeContract.from_spec(spec) for spec in TABLES.artifact_types
    )

    integer_contract = next(
        artifact
        for artifact in value.artifact_types
        if artifact.key.id == "scalar.integer"
    )
    text_contract = next(
        artifact for artifact in text.artifact_types if artifact.key.id == "scalar.text"
    )
    table_contract = next(
        artifact for artifact in table_contracts if artifact.key.id == "table.data"
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


def test_untrusted_artifact_query_cannot_gain_network_secrets_or_native_access() -> (
    None
):
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
        PluginNodeHttpEgressContract(configured_inputs=("base_url", "base_url"))

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

    undeclared = _http_egress_node(
        capabilities=(PluginRuntimeCapability.NETWORK_EGRESS,)
    )
    assert undeclared.http_egress is None


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
