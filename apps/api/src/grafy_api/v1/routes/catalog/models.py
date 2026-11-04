from typing import Any, Literal, Self, cast

from grafy_core.artifacts import (
    ArtifactBundleFormat,
    ArtifactConfirmationRule,
    ArtifactTypeSpec,
    ConfirmationRule,
    MaterializedJsonType,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    OutputPortSpec,
    PortShape,
)
from grafy_core.plugins import NodeRegistration, NodeSecretInput
from pydantic import BaseModel, Field, model_validator
from pydantic.errors import PydanticInvalidForJsonSchema

from grafy_api.catalog import (
    CatalogSnapshot,
)
from grafy_api.v1.models import (
    ApiResponse,
    ArtifactTypeKeyResponse,
    ArtifactTypeVariableIdentifier,
)

PortDirection = Literal["input", "output"]
CatalogOrigin = Literal["builtin"]
CatalogEntryKind = Literal["plugin"]


def _model_json_schema(model: type[BaseModel]) -> dict[str, object]:
    try:
        return cast(dict[str, object], model.model_json_schema())
    except PydanticInvalidForJsonSchema as exc:
        return {
            "title": model.__name__,
            "type": "object",
            "x-schema-error": str(exc),
            "properties": {
                name: {
                    "title": name,
                    "x-python-type": str(field.annotation),
                }
                for name, field in model.model_fields.items()
            },
        }


class FieldProjectionResponse(ApiResponse):
    path: list[str]
    target_artifact_type: ArtifactTypeKeyResponse
    title: str


class ArtifactExportFormatResponse(ApiResponse):
    format: str
    content_type: str
    filename: str


class ArtifactBundleContractResponse(ApiResponse):
    format: ArtifactBundleFormat
    version: int = Field(ge=1, strict=True)


class MagicSegmentResponse(ApiResponse):
    offset: int
    value: str


class ConfirmationRuleResponse(ApiResponse):
    rule: ConfirmationRule = "none"
    signatures: list[list[MagicSegmentResponse]] = Field(default_factory=list)

    @classmethod
    def from_rule(cls, rule: ArtifactConfirmationRule) -> Self:
        return cls(
            rule=rule.rule,
            signatures=[
                [
                    # Signature bytes cross the wire as lowercase hex.
                    MagicSegmentResponse(
                        offset=segment.offset, value=segment.value.hex()
                    )
                    for segment in signature.segments
                ]
                for signature in rule.signatures
            ],
        )


class ArtifactTypeSpecResponse(ApiResponse):
    key: ArtifactTypeKeyResponse
    title: str
    payload_schema: dict[str, object]
    field_projections: list[FieldProjectionResponse]
    materialized_json_type: MaterializedJsonType | None = None
    export_formats: list[ArtifactExportFormatResponse] = Field(
        default_factory=list,
    )
    extensions: list[str] = Field(default_factory=list)
    confirmation_rule: ConfirmationRuleResponse = Field(
        default_factory=ConfirmationRuleResponse,
    )
    bundle: ArtifactBundleContractResponse

    @classmethod
    def from_spec(cls, spec: ArtifactTypeSpec) -> Self:
        return cls(
            key=ArtifactTypeKeyResponse(
                id=spec.key.id,
                schema_version=spec.key.schema_version,
            ),
            title=spec.title,
            payload_schema=spec.payload_schema,
            field_projections=[
                FieldProjectionResponse(
                    path=list(projection.path),
                    target_artifact_type=ArtifactTypeKeyResponse(
                        id=projection.target.id,
                        schema_version=projection.target.schema_version,
                    ),
                    title=projection.title,
                )
                for projection in spec.field_projections
            ],
            materialized_json_type=spec.materialized_json_type,
            extensions=list(spec.extensions),
            confirmation_rule=ConfirmationRuleResponse.from_rule(
                spec.confirmation_rule
            ),
            export_formats=[
                ArtifactExportFormatResponse(
                    format=export_format.format,
                    content_type=export_format.content_type,
                    filename=export_format.filename,
                )
                for export_format in spec.export_formats
            ],
            bundle=ArtifactBundleContractResponse(
                format=spec.bundle.format,
                version=spec.bundle.version,
            ),
        )


class ArtifactConversionKeyResponse(ApiResponse):
    id: str
    version: int

    @classmethod
    def from_key(cls, key: ArtifactConversionKey) -> Self:
        return cls(id=key.id, version=key.version)


class ArtifactConversionSpecResponse(ApiResponse):
    key: ArtifactConversionKeyResponse
    source_artifact_type: ArtifactTypeKeyResponse
    target_artifact_type: ArtifactTypeKeyResponse
    title: str

    @classmethod
    def from_conversion(cls, conversion: ArtifactConversion[Any, Any]) -> Self:
        return cls(
            key=ArtifactConversionKeyResponse(
                id=conversion.key.id, version=conversion.key.version
            ),
            source_artifact_type=ArtifactTypeKeyResponse(
                id=conversion.source.id, schema_version=conversion.source.schema_version
            ),
            target_artifact_type=ArtifactTypeKeyResponse(
                id=conversion.target.id, schema_version=conversion.target.schema_version
            ),
            title=conversion.title,
        )


class PluginSpecResponse(ApiResponse):
    slug: str
    title: str
    origin: CatalogOrigin = "builtin"
    entry_kind: CatalogEntryKind = "plugin"

    @classmethod
    def from_builtin(cls, slug: str, title: str) -> Self:
        return cls(slug=slug, title=title, origin="builtin")


class PortResponse(ApiResponse):
    name: str
    title: str | None = None
    description: str | None = None
    direction: PortDirection
    artifact_type: ArtifactTypeKeyResponse | None = None
    artifact_type_variable: ArtifactTypeVariableIdentifier | None = None
    also_accepts: list[ArtifactTypeKeyResponse] = Field(default_factory=list)
    shape: PortShape
    accepted_shapes: list[PortShape]
    instance_plugs: bool = False
    variadic: bool = False
    required: bool = True
    shape_field: str | None = Field(
        default=None,
        description=(
            "Config field that chooses this port's shape for one node instance. "
            "Its value, 'one' or 'many', replaces shape and accepted_shapes."
        ),
    )

    @model_validator(mode="after")
    def validate_artifact_type_contract(self) -> Self:
        if (self.artifact_type is None) == (self.artifact_type_variable is None):
            raise ValueError(
                "Port must declare exactly one of artifact_type or "
                "artifact_type_variable"
            )
        if self.also_accepts and self.artifact_type is None:
            raise ValueError(
                "Port additional accepted artifact types require an artifact_type"
            )
        return self

    @classmethod
    def from_input_port(cls, port: InputPortSpec) -> Self:
        artifact_type: ArtifactTypeKeyResponse | None
        artifact_type_variable: str | None
        if isinstance(port.accepts, ArtifactTypeVariable):
            artifact_type = None
            artifact_type_variable = port.accepts.name
        else:
            artifact_type = ArtifactTypeKeyResponse.from_key(port.accepts)
            artifact_type_variable = None
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction="input",
            artifact_type=artifact_type,
            artifact_type_variable=artifact_type_variable,
            also_accepts=[
                ArtifactTypeKeyResponse.from_key(key) for key in port.also_accepts
            ],
            shape=port.shape,
            accepted_shapes=list(port.accepted_shapes),
            instance_plugs=port.instance_plugs,
            variadic=port.variadic,
            required=port.required,
            shape_field=port.shape_field,
        )

    @classmethod
    def from_output_port(cls, port: OutputPortSpec) -> Self:
        artifact_type: ArtifactTypeKeyResponse | None
        artifact_type_variable: str | None
        if isinstance(port.produces, ArtifactTypeVariable):
            artifact_type = None
            artifact_type_variable = port.produces.name
        else:
            artifact_type = ArtifactTypeKeyResponse.from_key(port.produces)
            artifact_type_variable = None
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction="output",
            artifact_type=artifact_type,
            artifact_type_variable=artifact_type_variable,
            shape=port.shape,
            accepted_shapes=[port.shape],
            instance_plugs=False,
            variadic=False,
            required=port.required,
            shape_field=port.shape_field,
        )


class NodeSecretInputResponse(ApiResponse):
    name: str
    config_dependencies: list[str]
    title: str
    description: str | None = None

    @classmethod
    def from_spec(cls, spec: NodeSecretInput) -> Self:
        return cls(
            name=spec.name,
            config_dependencies=list(spec.config_dependencies),
            title=spec.title,
            description=spec.description,
        )


class NodeSpecResponse(ApiResponse):
    origin: CatalogOrigin = "builtin"
    operator_id: str
    operator_version: int
    plugin_slug: str
    title: str
    description: str
    config_schema: dict[str, object]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    inputs: list[PortResponse]
    outputs: list[PortResponse]
    secret_inputs: list[NodeSecretInputResponse] = Field(default_factory=list)
    catalog_visible: bool = True
    runnable: bool = True

    @classmethod
    def from_registration(
        cls,
        registration: NodeRegistration,
        *,
        origin: CatalogOrigin = "builtin",
    ) -> Self:
        node_class = registration.node_class
        return cls(
            origin=origin,
            operator_id=node_class.operator_id,
            operator_version=node_class.operator_version,
            plugin_slug=registration.plugin_slug,
            title=registration.title,
            description=registration.description,
            config_schema=_model_json_schema(node_class.config_contract.model),
            input_schema=_model_json_schema(node_class.input_contract.model),
            output_schema=_model_json_schema(node_class.output_contract.model),
            inputs=[
                PortResponse.from_input_port(port)
                for port in node_class.input_contract.ports.values()
            ],
            outputs=[
                PortResponse.from_output_port(port)
                for port in node_class.output_contract.ports.values()
            ],
            secret_inputs=[
                NodeSecretInputResponse.from_spec(spec)
                for spec in registration.secret_inputs
            ],
            catalog_visible=registration.listed,
        )


class NodeRegistryResponse(ApiResponse):
    plugins: list[PluginSpecResponse]
    artifact_types: list[ArtifactTypeSpecResponse]
    artifact_conversions: list[ArtifactConversionSpecResponse]
    nodes: list[NodeSpecResponse]

    @classmethod
    def from_snapshot(
        cls,
        snapshot: CatalogSnapshot,
    ) -> Self:
        return cls(
            plugins=[
                PluginSpecResponse.from_builtin(plugin.slug, plugin.title)
                for plugin in snapshot.builtin_plugins
            ],
            artifact_types=[
                ArtifactTypeSpecResponse.from_spec(spec)
                for spec in snapshot.artifact_types
            ],
            artifact_conversions=[
                ArtifactConversionSpecResponse.from_conversion(conversion)
                for conversion in snapshot.conversions
            ],
            nodes=[
                NodeSpecResponse.from_registration(registration)
                for registration in snapshot.builtin_nodes
            ],
        )


__all__ = [
    "ArtifactBundleContractResponse",
    "ArtifactConversionKeyResponse",
    "ArtifactConversionSpecResponse",
    "ArtifactExportFormatResponse",
    "ArtifactTypeSpecResponse",
    "CatalogEntryKind",
    "CatalogOrigin",
    "ConfirmationRuleResponse",
    "FieldProjectionResponse",
    "MagicSegmentResponse",
    "NodeRegistryResponse",
    "NodeSecretInputResponse",
    "NodeSpecResponse",
    "PluginSpecResponse",
    "PortDirection",
    "PortResponse",
]
