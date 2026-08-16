"""Dynamic Grafy node for one exact, immutable agent-authored release."""

from typing import Annotated, Protocol, cast, override
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, NoConfig, NodeInput, NodeOutput
from grafy_core.domain.agent_authoring import (
    AgentPortDirection,
    GeneratedNodePort,
    NodeRelease,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    PortShape,
    derive_input_contract,
    derive_output_contract,
)
from grafy_core.ports.generated_execution import (
    GeneratedNodeExecutionRequest,
    GeneratedReleaseExecutorPort,
)
from grafy_core.source_bundles import GeneratedNodeBuildDocument


class GeneratedNodeContractError(ValueError):
    """A published release cannot be represented by the Grafy node runtime."""


class GeneratedNodeExecutionError(RuntimeError):
    """An isolated generated-node invocation failed or broke its contract."""


class GeneratedNodeInput(NodeInput):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, strict=True)


class GeneratedNodeOutput(NodeOutput):
    model_config = ConfigDict(extra="forbid", strict=True)


class _DynamicModelFactory(Protocol):
    def __call__(
        self,
        model_name: str,
        /,
        *,
        __base__: type[BaseModel],
        **field_definitions: object,
    ) -> type[BaseModel]: ...


_create_dynamic_model = cast(
    _DynamicModelFactory,
    cast(object, create_model),
)


def build_document_for_release(release: NodeRelease) -> GeneratedNodeBuildDocument:
    document = GeneratedNodeBuildDocument(
        source_digest=release.artifacts.source_digest,
        lock_digest=release.artifacts.lock_digest,
        tests_digest=release.artifacts.tests_digest,
        implementation_digest=release.artifacts.implementation_digest,
        manifest=release.manifest,
        capabilities=release.capabilities,
        runtime_image_digest=release.artifacts.runtime_image_digest,
        profile_digest=release.artifacts.profile_digest,
        runtime_artifact=release.artifacts.runtime_artifact,
    )
    if document.digest != release.artifacts.build_digest:
        raise GeneratedNodeContractError(
            f"Generated release {release.operator_id}@{release.operator_version} "
            "does not match its canonical build digest"
        )
    return document


def validate_generated_release_contract(
    release: NodeRelease,
    artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
) -> GeneratedNodeBuildDocument:
    """Validate the currently executable subset and return its canonical build."""

    build_document = build_document_for_release(release)
    capabilities = release.capabilities
    if capabilities.secret_refs or capabilities.object_store:
        raise GeneratedNodeContractError(
            f"Generated release {release.operator_id}@{release.operator_version} "
            "requires secrets or object-store access, which the isolated runtime "
            "does not yet support"
        )
    if capabilities.outbound_http_origins:
        raise GeneratedNodeContractError(
            f"Generated release {release.operator_id}@{release.operator_version} "
            "requires outbound HTTP, which remains disabled until runtime egress "
            "is independently enforced"
        )
    for port in (*release.manifest.inputs, *release.manifest.outputs):
        if port.direction is AgentPortDirection.INPUT and port.accepted_shapes != (
            port.shape,
        ):
            raise GeneratedNodeContractError(
                f"Generated input {port.name!r} must declare exactly one accepted shape"
            )
        if port.direction is AgentPortDirection.OUTPUT and not port.required:
            raise GeneratedNodeContractError(
                f"Generated output {port.name!r} must be required"
            )
        key = ArtifactTypeKey(
            port.artifact_type.id,
            port.artifact_type.schema_version,
        )
        artifact_type = artifact_types.get(key)
        if artifact_type is None:
            raise GeneratedNodeContractError(
                f"Generated port {port.name!r} references unavailable artifact type "
                f"{key.id}@{key.schema_version}"
            )
        if artifact_type.materialized_json_type not in {"string", "integer"}:
            raise GeneratedNodeContractError(
                f"Generated port {port.name!r} artifact type {key.id}@"
                f"{key.schema_version} is not materializable as a supported JSON scalar"
            )
    return build_document


class GeneratedNode(Node[NoConfig, GeneratedNodeInput, GeneratedNodeOutput]):
    operator_id = "generated.node.unbound"
    operator_version = 1
    plugin_slug = "generated.agent"
    title = "Unbound generated node"
    description = "An agent-authored node that has not been bound to a release."

    def __init__(
        self,
        release: NodeRelease,
        executor: GeneratedReleaseExecutorPort,
        artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
    ) -> None:
        self._release = release
        self._executor = executor
        self._build_document = validate_generated_release_contract(
            release,
            artifact_types,
        )

        input_model = _input_model_for(release, artifact_types)
        output_model = _output_model_for(release, artifact_types)
        dynamic_attributes = self.__dict__
        dynamic_attributes["operator_id"] = release.operator_id
        dynamic_attributes["operator_version"] = release.operator_version
        dynamic_attributes["plugin_slug"] = "generated.agent"
        dynamic_attributes["title"] = release.manifest.title
        dynamic_attributes["description"] = release.manifest.description
        dynamic_attributes["input_contract"] = derive_input_contract(input_model)
        dynamic_attributes["output_contract"] = derive_output_contract(output_model)

    @property
    def release(self) -> NodeRelease:
        return self._release

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: GeneratedNodeInput,
        /,
    ) -> GeneratedNodeOutput:
        request = GeneratedNodeExecutionRequest(
            request_id=uuid4(),
            workspace_id=context.workspace_id,
            workflow_run_id=context.workflow_run_id,
            node_run_id=context.node_run_id,
            graph_node_id=context.node_id,
            invocation_path=context.invocation_path,
            node_id=self._release.node_id,
            revision=self._release.revision,
            build_digest=self._release.artifacts.build_digest,
            build_document=self._build_document,
            inputs=cast(
                dict[str, JsonValue],
                inputs.model_dump(mode="json", exclude_none=False),
            ),
        )
        try:
            result = await self._executor.execute(request)
        except Exception as exc:
            raise GeneratedNodeExecutionError(
                f"Generated release {self.operator_id}@{self.operator_version} "
                f"failed for graph node {context.node_id or '<unknown>'!r}"
            ) from exc
        if result.request_id != request.request_id:
            raise GeneratedNodeExecutionError(
                f"Generated release {self.operator_id}@{self.operator_version} "
                "executor returned a mismatched request id"
            )
        output_model = cast(type[GeneratedNodeOutput], self.output_contract.model)
        try:
            return output_model.model_validate(result.outputs)
        except ValidationError as exc:
            raise GeneratedNodeExecutionError(
                f"Generated release {self.operator_id}@{self.operator_version} "
                "executor returned outputs that violate the published manifest"
            ) from exc


def _input_model_for(
    release: NodeRelease,
    artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
) -> type[GeneratedNodeInput]:
    fields: dict[str, tuple[object, object]] = {}
    for port in release.manifest.inputs:
        value_type = _port_value_type(port, artifact_types)
        annotation: object = value_type
        default: object = ...
        if not port.required:
            annotation = value_type | None
            default = None
        annotation = Annotated[
            annotation,
            InPort(
                ArtifactTypeKey(
                    port.artifact_type.id,
                    port.artifact_type.schema_version,
                )
            ),
            Field(
                title=port.name.replace("_", " ").title(),
                description=f"Agent-authored input {port.name}.",
            ),
        ]
        fields[port.name] = (annotation, default)
    return cast(
        type[GeneratedNodeInput],
        _create_dynamic_model(
            f"GeneratedNode_{release.node_id.hex}_r{release.revision}_Input",
            __base__=GeneratedNodeInput,
            **fields,
        ),
    )


def _output_model_for(
    release: NodeRelease,
    artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
) -> type[GeneratedNodeOutput]:
    fields: dict[str, tuple[object, object]] = {}
    for port in release.manifest.outputs:
        value_type = _port_value_type(port, artifact_types)
        annotation = Annotated[
            value_type,
            OutPort(
                ArtifactTypeKey(
                    port.artifact_type.id,
                    port.artifact_type.schema_version,
                )
            ),
            Field(
                title=port.name.replace("_", " ").title(),
                description=f"Agent-authored output {port.name}.",
            ),
        ]
        fields[port.name] = (annotation, ...)
    return cast(
        type[GeneratedNodeOutput],
        _create_dynamic_model(
            f"GeneratedNode_{release.node_id.hex}_r{release.revision}_Output",
            __base__=GeneratedNodeOutput,
            **fields,
        ),
    )


def _port_value_type(
    port: GeneratedNodePort,
    artifact_types: dict[ArtifactTypeKey, ArtifactTypeSpec],
) -> type[object]:
    key = ArtifactTypeKey(port.artifact_type.id, port.artifact_type.schema_version)
    artifact_type = artifact_types[key]
    scalar_type: type[object]
    if artifact_type.materialized_json_type == "string":
        scalar_type = str
    elif artifact_type.materialized_json_type == "integer":
        scalar_type = int
    else:
        raise GeneratedNodeContractError(
            f"Generated port {port.name!r} has unsupported materialized JSON type"
        )
    if port.shape is PortShape.MANY:
        return cast(type[object], list[scalar_type])
    return scalar_type


__all__ = [
    "GeneratedNode",
    "GeneratedNodeContractError",
    "GeneratedNodeExecutionError",
    "GeneratedNodeInput",
    "GeneratedNodeOutput",
    "build_document_for_release",
    "validate_generated_release_contract",
]
