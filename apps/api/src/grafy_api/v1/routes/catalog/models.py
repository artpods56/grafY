from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from pydantic.errors import PydanticInvalidForJsonSchema

from grafy_core.artifacts import (
    ArtifactBundleFormat,
    MaterializedJsonType,
)
from grafy_core.conversions import ArtifactConversionKey
from grafy_core.domain.module_library import (
    Module,
    ModuleRelease,
    ModulePublicationState,
)
from grafy_core.domain.modules import GraphModuleDefinition
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginArtifactConversionContract,
    PluginArtifactTypeContract,
    PluginNodeContract,
    PluginPortContract,
    PluginReleaseScope,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    OutputPortSpec,
    PortShape,
)
from grafy_core.operators.modules import GraphModuleNode
from grafy_core.plugins import NodeRegistration, NodeSecretInput
from grafy_core.ports.modules import GraphModuleExecutorPort

from grafy_api.plugins.runtime.admission import (
    PluginNonRunnableReason,
)
from grafy_api.v1.models import (
    ApiResponse,
    ArtifactTypeKeyResponse,
    ArtifactTypeVariableIdentifier,
    PluginReleasePinModel,
)

from grafy_api.catalog import (
    GRAPH_MODULE_PLUGIN_SLUG,
    CatalogSnapshot,
    CatalogNonRunnableReason,
    PluginReleaseReadiness,
)


PortDirection = Literal["input", "output"]
CatalogOrigin = Literal["builtin", "plugin", "module"]
CatalogEntryKind = Literal["plugin", "module"]


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


class ArtifactTypeSpecResponse(ApiResponse):
    key: ArtifactTypeKeyResponse
    title: str
    payload_schema: dict[str, object]
    field_projections: list[FieldProjectionResponse]
    materialized_json_type: MaterializedJsonType | None = None
    export_formats: list[ArtifactExportFormatResponse] = Field(
        default_factory=list,
    )
    bundle: ArtifactBundleContractResponse

    @classmethod
    def from_plugin_contract(cls, contract: PluginArtifactTypeContract) -> Self:
        return cls(
            key=ArtifactTypeKeyResponse(
                id=contract.key.id,
                schema_version=contract.key.schema_version,
            ),
            title=contract.title,
            payload_schema=contract.payload_schema,
            field_projections=[
                FieldProjectionResponse(
                    path=list(projection.path),
                    target_artifact_type=ArtifactTypeKeyResponse(
                        id=projection.target.id,
                        schema_version=projection.target.schema_version,
                    ),
                    title=projection.title,
                )
                for projection in contract.field_projections
            ],
            materialized_json_type=contract.materialized_json_type,
            export_formats=[
                ArtifactExportFormatResponse(
                    format=export_format.format,
                    content_type=export_format.content_type,
                    filename=export_format.filename,
                )
                for export_format in contract.export_formats
            ],
            bundle=ArtifactBundleContractResponse(
                format=contract.bundle.format,
                version=contract.bundle.version,
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
    def from_contract(cls, spec: PluginArtifactConversionContract) -> Self:
        return cls(
            key=ArtifactConversionKeyResponse(id=spec.key.id, version=spec.key.version),
            source_artifact_type=ArtifactTypeKeyResponse(
                id=spec.source.id, schema_version=spec.source.schema_version
            ),
            target_artifact_type=ArtifactTypeKeyResponse(
                id=spec.target.id, schema_version=spec.target.schema_version
            ),
            title=spec.title,
        )


class PluginSpecResponse(ApiResponse):
    slug: str
    title: str
    origin: CatalogOrigin = "plugin"
    entry_kind: CatalogEntryKind = "plugin"
    scope: PluginReleaseScope | None = None
    plugin_release: PluginReleasePinModel | None = None
    revision: int | None = Field(default=None, ge=1)
    publisher: str | None = None
    installation_scope: PluginReleaseScope | None = None
    runnable: bool = True
    non_runnable_reason: CatalogNonRunnableReason | None = None
    non_runnable_detail: str | None = None

    @model_validator(mode="after")
    def validate_catalog_identity(self) -> Self:
        if self.origin == "module":
            if self.entry_kind != "module":
                raise ValueError("Module catalog entries must use entry_kind=module")
            if self.scope is not None or self.installation_scope is not None:
                raise ValueError("Module catalog entries cannot declare Plugin scope")
            if self.plugin_release is not None or self.revision is not None:
                raise ValueError(
                    "Module catalog entries cannot declare a Plugin release"
                )
            if self.publisher is not None:
                raise ValueError("Module catalog entries cannot declare a publisher")
            return self
        if self.origin == "builtin":
            if self.entry_kind != "plugin":
                raise ValueError("Builtin catalog entries use entry_kind=plugin")
            if self.scope is not None or self.installation_scope is not None:
                raise ValueError("Builtin catalog entries cannot declare Plugin scope")
            if self.plugin_release is not None or self.revision is not None:
                raise ValueError(
                    "Builtin catalog entries cannot declare a Plugin release"
                )
            if self.publisher is not None:
                raise ValueError("Builtin catalog entries cannot declare a publisher")
            return self
        if self.scope is None:
            raise ValueError("Plugin catalog entries must declare Plugin scope")
        if self.installation_scope is None:
            object.__setattr__(self, "installation_scope", self.scope)
        if self.installation_scope is not self.scope:
            raise ValueError("installation_scope must match Plugin scope")
        if self.plugin_release is None or self.revision is None:
            raise ValueError("Plugin catalog entries must declare an exact release")
        if self.plugin_release.scope is not self.scope:
            raise ValueError("plugin_release scope must match Plugin scope")
        if self.plugin_release.slug != self.slug:
            raise ValueError("plugin_release slug must match Plugin slug")
        if self.plugin_release.revision != self.revision:
            raise ValueError("plugin_release revision must match revision")
        return self

    @classmethod
    def from_plugin_release(
        cls,
        release: InstalledPluginRelease,
        readiness: PluginReleaseReadiness,
    ) -> Self:
        publisher = release.release.published_by_platform_actor
        if publisher is None and release.release.published_by_user_id is not None:
            publisher = str(release.release.published_by_user_id)
        return cls(
            slug=release.release.slug,
            title=release.release.catalog.title,
            origin="plugin",
            scope=release.installation.scope,
            installation_scope=release.installation.scope,
            plugin_release=PluginReleasePinModel(
                scope=release.installation.scope,
                slug=release.release.slug,
                revision=release.release.revision,
            ),
            revision=release.release.revision,
            publisher=publisher,
            runnable=readiness.runnable,
            non_runnable_reason=readiness.reason,
            non_runnable_detail=readiness.detail,
        )

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
    shape: PortShape
    accepted_shapes: list[PortShape]
    instance_plugs: bool = False
    variadic: bool = False
    required: bool = True

    @model_validator(mode="after")
    def validate_artifact_type_contract(self) -> Self:
        if (self.artifact_type is None) == (self.artifact_type_variable is None):
            raise ValueError(
                "Port must declare exactly one of artifact_type or "
                "artifact_type_variable"
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
            shape=port.shape,
            accepted_shapes=list(port.accepted_shapes),
            instance_plugs=port.instance_plugs,
            variadic=port.variadic,
            required=port.required,
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
        )

    @classmethod
    def from_plugin_contract(cls, port: PluginPortContract) -> Self:
        artifact_type = (
            None
            if port.artifact_type is None
            else ArtifactTypeKeyResponse(
                id=port.artifact_type.id,
                schema_version=port.artifact_type.schema_version,
            )
        )
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction=port.direction,
            artifact_type=artifact_type,
            artifact_type_variable=port.artifact_type_variable,
            shape=port.shape,
            accepted_shapes=list(port.accepted_shapes),
            instance_plugs=port.instance_plugs,
            variadic=port.variadic,
            required=port.required,
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
    origin: CatalogOrigin = "plugin"
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
    module_graph_id: UUID | None = None
    module_graph_revision: int | None = Field(default=None, ge=1)
    module_id: UUID | None = None
    publication_state: ModulePublicationState | None = None
    is_current_library_release: bool | None = None
    catalog_visible: bool = True
    plugin_revision: int | None = Field(default=None, ge=1)
    plugin_release: PluginReleasePinModel | None = None
    runnable: bool = True
    non_runnable_reason: CatalogNonRunnableReason | None = None
    non_runnable_detail: str | None = None

    @model_validator(mode="after")
    def validate_module_identity(self) -> Self:
        if (self.module_graph_id is None) != (self.module_graph_revision is None):
            raise ValueError(
                "module_graph_id and module_graph_revision must be provided together"
            )
        if (self.plugin_release is None) != (self.plugin_revision is None):
            raise ValueError(
                "plugin_release and plugin_revision must be provided together"
            )
        if (
            self.plugin_release is not None
            and self.plugin_release.slug != self.plugin_slug
        ):
            raise ValueError("plugin_release slug must match plugin_slug")
        if (
            self.plugin_release is not None
            and self.plugin_release.revision != self.plugin_revision
        ):
            raise ValueError("plugin_release revision must match plugin_revision")
        return self

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
        )

    @classmethod
    def from_graph_module(
        cls,
        module: Module,
        release: ModuleRelease,
        definition: GraphModuleDefinition,
        module_executor: GraphModuleExecutorPort,
    ) -> Self:
        node = GraphModuleNode(definition, module_executor)
        return cls(
            origin="module",
            operator_id=node.operator_id,
            operator_version=node.operator_version,
            plugin_slug=GRAPH_MODULE_PLUGIN_SLUG,
            title=node.title,
            description=node.description,
            config_schema=_model_json_schema(node.config_contract.model),
            input_schema=_model_json_schema(node.input_contract.model),
            output_schema=_model_json_schema(node.output_contract.model),
            inputs=[
                PortResponse.from_input_port(port)
                for port in node.input_contract.ports.values()
            ],
            outputs=[
                PortResponse.from_output_port(port)
                for port in node.output_contract.ports.values()
            ],
            module_graph_id=definition.reference.graph_id,
            module_graph_revision=definition.reference.revision,
            module_id=module.id,
            publication_state=module.publication_state,
            is_current_library_release=module.current_library_release
            == release.revision,
            catalog_visible=module.current_library_release == release.revision,
        )

    @classmethod
    def from_plugin_release(
        cls,
        release: InstalledPluginRelease,
        contract: PluginNodeContract,
        readiness: PluginReleaseReadiness,
    ) -> Self:
        return cls(
            origin="plugin",
            operator_id=contract.operator_id,
            operator_version=contract.operator_version,
            plugin_slug=release.release.slug,
            title=contract.title,
            description=contract.description,
            config_schema=contract.config_schema,
            input_schema=contract.input_schema,
            output_schema=contract.output_schema,
            inputs=[
                PortResponse.from_plugin_contract(port) for port in contract.inputs
            ],
            outputs=[
                PortResponse.from_plugin_contract(port) for port in contract.outputs
            ],
            secret_inputs=[
                NodeSecretInputResponse(
                    name=secret.name,
                    config_dependencies=list(secret.config_dependencies),
                    title=secret.title,
                    description=secret.description,
                )
                for secret in contract.secret_inputs
            ],
            plugin_revision=release.release.revision,
            plugin_release=PluginReleasePinModel(
                scope=release.installation.scope,
                slug=release.release.slug,
                revision=release.release.revision,
            ),
            runnable=readiness.runnable,
            non_runnable_reason=readiness.reason,
            non_runnable_detail=readiness.detail,
        )


class UnavailableGraphModuleResponse(ApiResponse):
    graph_id: UUID
    revision: int = Field(ge=1, strict=True)
    name: str
    reason: str


class NodeRegistryResponse(ApiResponse):
    plugins: list[PluginSpecResponse]
    artifact_types: list[ArtifactTypeSpecResponse]
    artifact_conversions: list[ArtifactConversionSpecResponse]
    nodes: list[NodeSpecResponse]
    unavailable_modules: list[UnavailableGraphModuleResponse] = Field(
        default_factory=list
    )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: CatalogSnapshot,
        module_executor: GraphModuleExecutorPort,
    ) -> Self:
        return cls(
            plugins=[
                PluginSpecResponse(
                    slug=GRAPH_MODULE_PLUGIN_SLUG,
                    title="Workspace library",
                    origin="module",
                    entry_kind="module",
                )
            ]
            + [
                PluginSpecResponse.from_builtin(plugin.slug, plugin.title)
                for plugin in snapshot.builtin_plugins
            ]
            + [
                PluginSpecResponse.from_plugin_release(
                    release,
                    snapshot.release_readiness[release.release.slug],
                )
                for release in snapshot.releases
            ],
            artifact_types=[
                ArtifactTypeSpecResponse.from_plugin_contract(contract)
                for contract in snapshot.artifact_contracts
            ],
            artifact_conversions=[
                ArtifactConversionSpecResponse.from_contract(conversion)
                for conversion in snapshot.conversions
            ],
            nodes=[
                NodeSpecResponse.from_registration(
                    registration,
                    origin="module",
                )
                for registration in snapshot.module_boundary_nodes
            ]
            + [
                NodeSpecResponse.from_registration(registration)
                for registration in snapshot.builtin_nodes
            ]
            + [
                NodeSpecResponse.from_graph_module(
                    module, release, definition, module_executor
                )
                for module, release, definition in snapshot.modules
            ]
            + [
                NodeSpecResponse.from_plugin_release(
                    release,
                    contract,
                    snapshot.node_readiness[
                        (
                            release.release.slug,
                            contract.operator_id,
                            contract.operator_version,
                        )
                    ],
                )
                for release in snapshot.releases
                for contract in release.release.catalog.nodes
            ],
            unavailable_modules=[],
        )


__all__ = [
    "ArtifactBundleContractResponse",
    "ArtifactConversionKeyResponse",
    "ArtifactConversionSpecResponse",
    "ArtifactExportFormatResponse",
    "ArtifactTypeSpecResponse",
    "CatalogEntryKind",
    "CatalogOrigin",
    "CatalogNonRunnableReason",
    "FieldProjectionResponse",
    "NodeRegistryResponse",
    "NodeSecretInputResponse",
    "NodeSpecResponse",
    "PluginNonRunnableReason",
    "PluginReleaseReadiness",
    "PluginSpecResponse",
    "PortDirection",
    "PortResponse",
    "UnavailableGraphModuleResponse",
]
