from typing import Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from pydantic.errors import PydanticInvalidForJsonSchema

from grafy_core.artifacts import (
    ArtifactExportFormat,
    ArtifactFieldProjection,
    ArtifactTypeSpec,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.domain.module_library import ModulePublicationState
from grafy_core.domain.agent_authoring import (
    DraftNode,
    DraftNodeStatus,
    GeneratedNodeManifest,
    GeneratedNodePort,
    NodeBuildAttempt,
    NodeRelease,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    OutputPortSpec,
    PortShape,
)
from grafy_core.operators.generated import (
    GeneratedNodeContractError,
    validate_generated_release_contract,
)
from grafy_core.operators.modules import GraphModuleNode
from grafy_core.plugins import (
    InstalledPlugin,
    NodeRegistration,
    NodeSecretInput,
    PluginOrigin,
    PluginRegistry,
)
from grafy_core.ports.modules import GraphModuleExecutorPort

from grafy_api.v1.models import (
    ApiResponse,
    ArtifactTypeKeyResponse,
    ArtifactTypeVariableIdentifier,
)

from .services import (
    AGENT_AUTHORED_PLUGIN_SLUG,
    GRAPH_MODULE_PLUGIN_SLUG,
    GraphModuleCatalogEntry,
    GraphModuleCatalogListing,
    UnavailableGraphModule,
)


PortDirection = Literal["input", "output"]


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

    @classmethod
    def from_projection(cls, projection: ArtifactFieldProjection) -> Self:
        return cls(
            path=list(projection.path),
            target_artifact_type=ArtifactTypeKeyResponse.from_key(projection.target),
            title=projection.title,
        )


class ArtifactExportFormatResponse(ApiResponse):
    format: str
    content_type: str
    filename: str

    @classmethod
    def from_export_format(cls, export_format: ArtifactExportFormat) -> Self:
        return cls(
            format=export_format.format,
            content_type=export_format.content_type,
            filename=export_format.filename,
        )


class ArtifactTypeSpecResponse(ApiResponse):
    key: ArtifactTypeKeyResponse
    title: str
    payload_schema: dict[str, object]
    field_projections: list[FieldProjectionResponse]
    export_formats: list[ArtifactExportFormatResponse] = Field(
        default_factory=list,
    )

    @classmethod
    def from_spec(cls, spec: ArtifactTypeSpec) -> Self:
        return cls(
            key=ArtifactTypeKeyResponse.from_key(spec.key),
            title=spec.title,
            payload_schema=spec.payload_schema,
            field_projections=[
                FieldProjectionResponse.from_projection(projection)
                for projection in spec.field_projections
            ],
            export_formats=[
                ArtifactExportFormatResponse.from_export_format(export_format)
                for export_format in spec.export_formats
            ],
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
    def from_spec[SourceT, TargetT](
        cls,
        spec: ArtifactConversion[SourceT, TargetT],
    ) -> Self:
        return cls(
            key=ArtifactConversionKeyResponse.from_key(spec.key),
            source_artifact_type=ArtifactTypeKeyResponse.from_key(spec.source),
            target_artifact_type=ArtifactTypeKeyResponse.from_key(spec.target),
            title=spec.title,
        )


class PluginSpecResponse(ApiResponse):
    slug: str
    title: str
    origin: PluginOrigin

    @classmethod
    def from_plugin(cls, plugin: InstalledPlugin) -> Self:
        return cls(
            slug=plugin.slug,
            title=plugin.title,
            origin=plugin.origin,
        )


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
    def from_generated_port(cls, port: GeneratedNodePort) -> Self:
        accepted_shapes = list(port.accepted_shapes)
        if not accepted_shapes:
            accepted_shapes = [port.shape]
        return cls(
            name=port.name,
            title=port.name.replace("_", " ").title(),
            direction=port.direction.value,
            artifact_type=ArtifactTypeKeyResponse(
                id=port.artifact_type.id,
                schema_version=port.artifact_type.schema_version,
            ),
            shape=port.shape,
            accepted_shapes=accepted_shapes,
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


class AgentNodeAuthoringResponse(ApiResponse):
    draft_node_id: UUID
    status: DraftNodeStatus
    runnable: bool
    release_revision: int | None = Field(default=None, ge=1)


def agent_release_is_runnable(
    release: NodeRelease,
    registry: PluginRegistry,
    *,
    generated_execution_available: bool,
) -> bool:
    if not generated_execution_available:
        return False
    artifact_types = {
        artifact_type.key: artifact_type for artifact_type in registry.artifact_types
    }
    try:
        validate_generated_release_contract(release, artifact_types)
    except GeneratedNodeContractError:
        return False
    return True


class NodeSpecResponse(ApiResponse):
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
    agent_authoring: AgentNodeAuthoringResponse | None = None

    @model_validator(mode="after")
    def validate_module_identity(self) -> Self:
        if (self.module_graph_id is None) != (self.module_graph_revision is None):
            raise ValueError(
                "module_graph_id and module_graph_revision must be provided together"
            )
        return self

    @classmethod
    def from_registration(cls, registration: NodeRegistration) -> Self:
        node_class = registration.node_class
        return cls(
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
        entry: GraphModuleCatalogEntry,
        module_executor: GraphModuleExecutorPort,
    ) -> Self:
        definition = entry.definition
        node = GraphModuleNode(definition, module_executor)
        return cls(
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
            module_id=entry.module_id,
            publication_state=entry.publication_state,
            is_current_library_release=entry.is_current_library_release,
            catalog_visible=entry.catalog_visible,
        )

    @classmethod
    def from_agent_draft(cls, draft: DraftNode) -> Self:
        return cls.from_agent_manifest(
            operator_id=draft.operator_id,
            operator_version=draft.operator_version,
            manifest=draft.provisional_manifest,
            authoring=AgentNodeAuthoringResponse(
                draft_node_id=draft.id,
                status=draft.status,
                runnable=False,
                release_revision=None,
            ),
        )

    @classmethod
    def from_agent_build(
        cls,
        draft: DraftNode,
        build: NodeBuildAttempt,
    ) -> Self:
        return cls.from_agent_manifest(
            operator_id=draft.operator_id,
            operator_version=draft.operator_version,
            manifest=build.manifest or draft.provisional_manifest,
            authoring=AgentNodeAuthoringResponse(
                draft_node_id=draft.id,
                status=draft.status,
                runnable=False,
                release_revision=None,
            ),
        )

    @classmethod
    def from_agent_release(cls, release: NodeRelease, *, runnable: bool) -> Self:
        return cls.from_agent_manifest(
            operator_id=release.operator_id,
            operator_version=release.operator_version,
            manifest=release.manifest,
            authoring=AgentNodeAuthoringResponse(
                draft_node_id=release.draft_node_id,
                status=DraftNodeStatus.PUBLISHED,
                runnable=runnable,
                release_revision=release.revision,
            ),
        )

    @classmethod
    def from_agent_manifest(
        cls,
        *,
        operator_id: str,
        operator_version: int,
        manifest: GeneratedNodeManifest,
        authoring: AgentNodeAuthoringResponse,
    ) -> Self:
        input_properties = {
            port.name: {"title": port.name.replace("_", " ").title()}
            for port in manifest.inputs
        }
        output_properties = {
            port.name: {"title": port.name.replace("_", " ").title()}
            for port in manifest.outputs
        }
        return cls(
            operator_id=operator_id,
            operator_version=operator_version,
            plugin_slug=AGENT_AUTHORED_PLUGIN_SLUG,
            title=manifest.title,
            description=manifest.description,
            config_schema={
                "title": "GeneratedNodeConfig",
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            input_schema={
                "title": "GeneratedNodeInput",
                "type": "object",
                "properties": input_properties,
                "required": [
                    port.name for port in manifest.inputs if port.required
                ],
            },
            output_schema={
                "title": "GeneratedNodeOutput",
                "type": "object",
                "properties": output_properties,
                "required": [
                    port.name for port in manifest.outputs if port.required
                ],
            },
            inputs=[PortResponse.from_generated_port(port) for port in manifest.inputs],
            outputs=[
                PortResponse.from_generated_port(port) for port in manifest.outputs
            ],
            agent_authoring=authoring,
        )
class UnavailableGraphModuleResponse(ApiResponse):
    graph_id: UUID
    revision: int = Field(ge=1, strict=True)
    name: str
    reason: str

    @classmethod
    def from_module(cls, module: UnavailableGraphModule) -> Self:
        return cls(
            graph_id=module.graph_id,
            revision=module.revision,
            name=module.name,
            reason=module.reason,
        )


class NodeRegistryResponse(ApiResponse):
    plugins: list[PluginSpecResponse]
    artifact_types: list[ArtifactTypeSpecResponse]
    artifact_conversions: list[ArtifactConversionSpecResponse]
    nodes: list[NodeSpecResponse]
    unavailable_modules: list[UnavailableGraphModuleResponse] = Field(
        default_factory=list
    )

    @classmethod
    def from_registry(
        cls,
        registry: PluginRegistry,
        module_listing: GraphModuleCatalogListing,
        module_executor: GraphModuleExecutorPort,
        *,
        agent_drafts: list[DraftNode] | None = None,
        agent_releases: list[NodeRelease] | None = None,
        generated_execution_available: bool = False,
    ) -> Self:
        drafts = agent_drafts or []
        releases = agent_releases or []
        released_identities = {
            (release.operator_id, release.operator_version) for release in releases
        }
        agent_nodes = [
            NodeSpecResponse.from_agent_draft(draft)
            for draft in drafts
            if draft.status is not DraftNodeStatus.PUBLISHED
            and (draft.operator_id, draft.operator_version)
            not in released_identities
        ]
        for release in releases:
            agent_nodes.append(
                NodeSpecResponse.from_agent_release(
                    release,
                    runnable=agent_release_is_runnable(
                        release,
                        registry,
                        generated_execution_available=(
                            generated_execution_available
                        ),
                    ),
                )
            )
        return cls(
            plugins=[
                PluginSpecResponse.from_plugin(plugin) for plugin in registry.plugins
            ]
            + [
                PluginSpecResponse(
                    slug=GRAPH_MODULE_PLUGIN_SLUG,
                    title="Workspace library",
                    origin=PluginOrigin.MODULE,
                ),
                PluginSpecResponse(
                    slug=AGENT_AUTHORED_PLUGIN_SLUG,
                    title="Agent-authored nodes",
                    origin=PluginOrigin.AGENT,
                ),
            ],
            artifact_types=[
                ArtifactTypeSpecResponse.from_spec(spec)
                for spec in registry.artifact_types
            ],
            artifact_conversions=[
                ArtifactConversionSpecResponse.from_spec(spec)
                for spec in registry.artifact_conversions
            ],
            nodes=[
                NodeSpecResponse.from_registration(registration)
                for registration in registry.nodes
            ]
            + [
                NodeSpecResponse.from_graph_module(entry, module_executor)
                for entry in module_listing.entries
            ]
            + agent_nodes,
            unavailable_modules=[
                UnavailableGraphModuleResponse.from_module(module)
                for module in module_listing.unavailable
            ],
        )


__all__ = [
    "AgentNodeAuthoringResponse",
    "ArtifactConversionKeyResponse",
    "ArtifactConversionSpecResponse",
    "ArtifactExportFormatResponse",
    "ArtifactTypeSpecResponse",
    "FieldProjectionResponse",
    "NodeRegistryResponse",
    "NodeSecretInputResponse",
    "NodeSpecResponse",
    "PluginSpecResponse",
    "PortDirection",
    "PortResponse",
    "UnavailableGraphModuleResponse",
]
