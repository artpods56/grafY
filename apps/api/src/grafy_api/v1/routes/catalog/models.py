from typing import Any, Literal, Self, cast

from grafy_core.artifacts import (
    ArtifactBundleFormat,
    ArtifactConfirmationRule,
    ArtifactPreviewKind,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    ConfirmationRule,
    MaterializedJsonType,
)
from grafy_core.conversions import ArtifactConversionKey, Conversion
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    OutputPortSpec,
    PortShape,
    ServiceContractKey,
)
from grafy_core.plugins import NodeRegistration, NodeSecretInput
from grafy_core.service_contracts import ServiceContract
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
PortKind = Literal["artifact", "service"]
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
    preview_kind: ArtifactPreviewKind = ArtifactPreviewKind.FILE

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
            preview_kind=spec.preview_kind,
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
    def from_conversion(cls, conversion: Conversion[Any, Any]) -> Self:
        source = conversion.source.spec.key
        target = conversion.target.spec.key
        return cls(
            key=ArtifactConversionKeyResponse(
                id=conversion.id, version=conversion.version
            ),
            source_artifact_type=ArtifactTypeKeyResponse(
                id=source.id, schema_version=source.schema_version
            ),
            target_artifact_type=ArtifactTypeKeyResponse(
                id=target.id, schema_version=target.schema_version
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


class ServiceContractKeyResponse(ApiResponse):
    id: str
    version: int = Field(ge=1, strict=True)

    @classmethod
    def from_key(cls, key: ServiceContractKey) -> Self:
        return cls(id=key.id, version=key.version)


class ServiceContractResponse(ApiResponse):
    id: str
    version: int = Field(ge=1, strict=True)
    title: str

    @classmethod
    def from_contract(cls, contract: ServiceContract) -> Self:
        return cls(id=contract.id, version=contract.version, title=contract.title)


class PortResponse(ApiResponse):
    name: str
    title: str | None = None
    description: str | None = None
    direction: PortDirection
    kind: PortKind = "artifact"
    artifact_type: ArtifactTypeKeyResponse | None = None
    artifact_type_variable: ArtifactTypeVariableIdentifier | None = None
    also_accepts: list[ArtifactTypeKeyResponse] = Field(default_factory=list)
    service_contracts: list[ServiceContractKeyResponse] = Field(default_factory=list)
    features: list[str] = Field(
        default_factory=list,
        description=(
            "Feature strings a service output's implementation declares, so the "
            "workbench can mute ports a connected provider does not produce."
        ),
    )
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
    agent_default: Literal["hidden"] | None = Field(
        default=None,
        description=(
            "'hidden' when an Agent tool link leaves this input to the Graph unless told "
            "otherwise. Absent means the input is offered to the model as a parameter. "
            "A service input is always hidden."
        ),
    )

    @model_validator(mode="after")
    def validate_port_contract(self) -> Self:
        if self.kind == "service":
            if (
                self.artifact_type is not None
                or self.artifact_type_variable is not None
                or self.also_accepts
            ):
                raise ValueError(
                    "Service port cannot declare an artifact type or variable"
                )
            if not self.service_contracts:
                raise ValueError("Service port must name at least one service contract")
            return self
        if self.service_contracts:
            raise ValueError("Artifact port cannot declare a service contract")
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
        if port.kind == "service":
            return cls(
                name=port.name,
                title=port.title,
                description=port.description,
                direction="input",
                kind="service",
                artifact_type=None,
                artifact_type_variable=None,
                also_accepts=[],
                service_contracts=[
                    ServiceContractKeyResponse.from_key(key)
                    for key in port.service_contracts
                ],
                features=[],
                shape=port.shape,
                accepted_shapes=list(port.accepted_shapes),
                instance_plugs=port.instance_plugs,
                variadic=port.variadic,
                required=port.required,
                shape_field=port.shape_field,
                agent_default="hidden",
            )
        artifact_type: ArtifactTypeKeyResponse | None
        artifact_type_variable: str | None
        if isinstance(port.accepts, ArtifactTypeVariable):
            artifact_type = None
            artifact_type_variable = port.accepts.name
        else:
            if not isinstance(port.accepts, ArtifactTypeKey):
                raise ValueError(
                    f"Artifact input port {port.name!r} must declare an artifact type"
                )
            artifact_type = ArtifactTypeKeyResponse.from_key(port.accepts)
            artifact_type_variable = None
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction="input",
            kind="artifact",
            artifact_type=artifact_type,
            artifact_type_variable=artifact_type_variable,
            also_accepts=[
                ArtifactTypeKeyResponse.from_key(key) for key in port.also_accepts
            ],
            service_contracts=[],
            shape=port.shape,
            accepted_shapes=list(port.accepted_shapes),
            instance_plugs=port.instance_plugs,
            variadic=port.variadic,
            required=port.required,
            shape_field=port.shape_field,
            agent_default=None if port.agent_default == "fill" else port.agent_default,
        )

    @classmethod
    def from_output_port(cls, port: OutputPortSpec) -> Self:
        if port.kind == "service":
            return cls(
                name=port.name,
                title=port.title,
                description=port.description,
                direction="output",
                kind="service",
                artifact_type=None,
                artifact_type_variable=None,
                also_accepts=[],
                service_contracts=[
                    ServiceContractKeyResponse.from_key(key)
                    for key in port.service_contracts
                ],
                features=list(port.features),
                shape=port.shape,
                accepted_shapes=[port.shape],
                instance_plugs=False,
                variadic=False,
                required=port.required,
                shape_field=port.shape_field,
            )
        artifact_type: ArtifactTypeKeyResponse | None
        artifact_type_variable: str | None
        if isinstance(port.produces, ArtifactTypeVariable):
            artifact_type = None
            artifact_type_variable = port.produces.name
        else:
            if not isinstance(port.produces, ArtifactTypeKey):
                raise ValueError(
                    f"Artifact output port {port.name!r} must declare an artifact type"
                )
            artifact_type = ArtifactTypeKeyResponse.from_key(port.produces)
            artifact_type_variable = None
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction="output",
            kind="artifact",
            artifact_type=artifact_type,
            artifact_type_variable=artifact_type_variable,
            service_contracts=[],
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
    service_contracts: list[ServiceContractResponse] = Field(default_factory=list)
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
            service_contracts=[
                ServiceContractResponse.from_contract(contract)
                for contract in snapshot.service_contracts
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
    "PortKind",
    "PortResponse",
    "ServiceContractKeyResponse",
    "ServiceContractResponse",
]
