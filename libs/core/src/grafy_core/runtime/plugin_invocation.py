"""Caller-owned Plugin invocation seam and its release-pinned proxy.

The compiler resolves one exact persisted ``PluginRelease`` and builds a
``PluginReleaseNode`` from the serialized catalog contract only; no
Plugin Python is imported. The proxy keeps ``ArtifactRef`` containers intact on
the way in, delegates through the ``PluginInvoker`` port, and returns only
host-minted refs so the existing persister passes them through unchanged.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol, cast, override
from uuid import UUID

from pydantic import ConfigDict, Field, create_model

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginArtifactBundleContract,
    PluginArtifactReferenceContract,
    PluginNodeContract,
    PluginPortContract,
    PluginReleaseIdentity,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    ArtifactTypeVariable,
    ConfigContract,
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    derive_input_contract,
    derive_output_contract,
)
from grafy_core.plugins import NodeCachePolicy
from grafy_core.runtime.plugin_protocol import PluginFailureCode


class PluginInvocationError(RuntimeError):
    """A Plugin invocation failed inside the configured adapter."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: PluginFailureCode | None = None,
        user_facing: bool = False,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.user_facing = user_facing


@dataclass(frozen=True, slots=True)
class PluginInvocationRequest:
    """One scalar Plugin invocation request with ref-preserving inputs."""

    release: PluginReleaseIdentity
    contract: PluginNodeContract
    artifact_type_bindings: Mapping[str, ArtifactTypeKey]
    config: JsonObject
    inputs: Mapping[str, object]
    workspace_id: UUID
    artifact_bundle_contracts: Mapping[
        ArtifactTypeKey,
        PluginArtifactBundleContract,
    ] = field(default_factory=dict[ArtifactTypeKey, PluginArtifactBundleContract])
    artifact_reference_contracts: Mapping[
        ArtifactTypeKey,
        tuple[PluginArtifactReferenceContract, ...],
    ] = field(
        default_factory=dict[
            ArtifactTypeKey,
            tuple[PluginArtifactReferenceContract, ...],
        ]
    )
    required_capabilities: tuple[PluginRuntimeCapability, ...] = ()
    node_id: str | None = None
    workflow_run_id: UUID | None = None
    invocation_index: int | None = None
    secret_graph_id: UUID | None = None
    secret_graph_revision: int | None = None
    progress_context: NodeExecutionContext | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                {
                    PluginRuntimeCapability(capability)
                    for capability in self.required_capabilities
                },
                key=lambda capability: capability.value,
            )
        )
        if not normalized:
            normalized = self.contract.required_capabilities
        if normalized != self.contract.required_capabilities:
            raise ValueError(
                "Plugin invocation capability profile must match its node contract"
            )
        object.__setattr__(self, "required_capabilities", normalized)


@dataclass(frozen=True, slots=True)
class PluginInvocationResult:
    """Validated host-minted artifact references produced by one invocation."""

    outputs: dict[str, ArtifactRef | ArtifactRefSequence] = field(
        default_factory=dict[str, ArtifactRef | ArtifactRefSequence],
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outputs",
            dict(self.outputs),
        )


class PluginInvoker(Protocol):
    async def invoke(
        self,
        request: PluginInvocationRequest,
        /,
    ) -> PluginInvocationResult: ...


class PluginReleaseNodeConfig(NodeConfig):
    """Host-side permissive configuration envelope for a pinned release node.

    Authoritative Plugin config validation stays behind the guest boundary;
    the host can only safely reconstruct that the submitted configuration is
    a JSON object.
    """

    model_config: ConfigDict = ConfigDict(extra="allow")


class PluginReleaseNodeError(RuntimeError):
    pass


class PluginReleaseNode[
    ConfigT: NodeConfig,
    InputT: NodeInput,
    OutputT: NodeOutput,
](Node[ConfigT, InputT, OutputT]):
    """Executes one operator of one exact Plugin release.

    Contracts come from the persisted release catalog. Inputs stay authorized
    ``ArtifactRef`` / ``ArtifactRefSequence`` containers, so MAP and ONCE
    semantics are owned entirely by the ordinary node execution pipeline.
    """

    operator_id = "plugin.release.unbound"
    operator_version = 1
    plugin_slug = "plugin.release"
    title = "Unbound Plugin node"
    description = "A Plugin node that has not been bound to a release."
    cache_policy = NodeCachePolicy.NEVER

    def __init__(
        self,
        release: InstalledPluginRelease,
        contract: PluginNodeContract,
        invoker: PluginInvoker,
        artifact_type_bindings: Mapping[str, ArtifactTypeKey] | None = None,
    ) -> None:
        matched = [
            declared
            for declared in release.release.catalog.nodes
            if declared.operator_id == contract.operator_id
            and declared.operator_version == contract.operator_version
        ]
        if not matched or matched[0] != contract:
            raise PluginReleaseNodeError(
                f"Plugin node contract {contract.operator_id}@"
                f"{contract.operator_version} does not match the serialized "
                f"catalog of {release.release.slug} revision {release.release.revision}"
            )
        self._release = release
        self._contract = contract
        self._invoker = invoker
        self._identity = PluginReleaseIdentity.from_release(release)
        self._artifact_type_bindings = dict(artifact_type_bindings or {})
        self._artifact_bundle_contracts = {
            ArtifactTypeKey(
                artifact.key.id,
                artifact.key.schema_version,
            ): artifact.bundle
            for artifact in (
                *release.release.catalog.artifact_types,
                *release.release.catalog.artifact_type_dependencies,
            )
        }
        self._artifact_reference_contracts = {
            ArtifactTypeKey(
                artifact.key.id,
                artifact.key.schema_version,
            ): artifact.references
            for artifact in (
                *release.release.catalog.artifact_types,
                *release.release.catalog.artifact_type_dependencies,
            )
            if artifact.references
        }

        dynamic_attributes = self.__dict__
        dynamic_attributes["operator_id"] = contract.operator_id
        dynamic_attributes["operator_version"] = contract.operator_version
        dynamic_attributes["plugin_slug"] = release.release.slug
        dynamic_attributes["title"] = contract.title
        dynamic_attributes["description"] = contract.description
        dynamic_attributes["cache_policy"] = contract.cache_policy
        input_model = _input_model_for(contract, self._artifact_type_bindings)
        output_model = _output_model_for(contract, self._artifact_type_bindings)
        dynamic_attributes["config_contract"] = _CONFIG_CONTRACT
        dynamic_attributes["input_contract"] = derive_input_contract(input_model)
        dynamic_attributes["output_contract"] = derive_output_contract(output_model)

    @property
    def release(self) -> InstalledPluginRelease:
        return self._release

    @property
    def contract(self) -> PluginNodeContract:
        return self._contract

    @property
    def release_identity(self) -> PluginReleaseIdentity:
        return self._identity

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ConfigT,
        inputs: InputT,
        /,
    ) -> OutputT:
        request_inputs: dict[str, object] = {}
        for port in self._contract.inputs:
            value = getattr(inputs, port.name)
            if value is None and not port.required:
                continue
            _require_ref_container(port, value)
            request_inputs[port.name] = value

        try:
            result = await self._invoker.invoke(
                PluginInvocationRequest(
                    release=self._identity,
                    contract=self._contract,
                    artifact_type_bindings=self._artifact_type_bindings,
                    config=config.model_dump(mode="json", by_alias=True),
                    inputs=request_inputs,
                    artifact_bundle_contracts=self._artifact_bundle_contracts,
                    artifact_reference_contracts=(self._artifact_reference_contracts),
                    required_capabilities=self._contract.required_capabilities,
                    workspace_id=context.workspace_id,
                    node_id=context.node_id,
                    workflow_run_id=context.workflow_run_id,
                    invocation_index=context.invocation_index,
                    secret_graph_id=context.secret_graph_id,
                    secret_graph_revision=context.secret_graph_revision,
                    progress_context=context,
                )
            )
        except PluginInvocationError:
            raise
        except Exception as exc:
            raise PluginInvocationError(
                f"Plugin invoker for {self._release.release.slug} revision "
                f"{self._release.release.revision} operator "
                f"{self._contract.operator_id}@"
                f"{self._contract.operator_version} failed: {exc}"
            ) from exc

        output_values = _validated_outputs(
            self._contract,
            result.outputs,
            self._artifact_type_bindings,
        )
        output_model = cast(type[OutputT], self.output_contract.model)
        return output_model.model_validate(output_values)


_CONFIG_CONTRACT: ConfigContract[PluginReleaseNodeConfig] = ConfigContract(
    model=PluginReleaseNodeConfig,
)


def _require_ref_container(
    port: PluginPortContract,
    value: object,
) -> None:
    if port.instance_plugs or port.variadic:
        if not isinstance(value, list):
            raise PluginReleaseNodeError(
                f"Plugin input {port.name!r} expected one authorized "
                "artifact reference container per incoming edge"
            )
        expected_type = ArtifactRefSequence if port.shape == "many" else ArtifactRef
        if not all(
            isinstance(item, expected_type) for item in cast(list[object], value)
        ):
            raise PluginReleaseNodeError(
                f"Plugin input {port.name!r} received a reference "
                "container with the wrong cardinality"
            )
        return
    if port.shape == "many":
        if not isinstance(value, ArtifactRefSequence):
            raise PluginReleaseNodeError(
                f"Plugin input {port.name!r} expected an "
                f"ArtifactRefSequence, got {type(value).__name__}"
            )
        return
    if not isinstance(value, ArtifactRef):
        raise PluginReleaseNodeError(
            f"Plugin input {port.name!r} expected an ArtifactRef, "
            f"got {type(value).__name__}"
        )


def _validated_outputs(
    contract: PluginNodeContract,
    outputs: Mapping[str, ArtifactRef | ArtifactRefSequence],
    artifact_type_bindings: Mapping[str, ArtifactTypeKey],
) -> dict[str, object]:
    expected_names = {port.name for port in contract.outputs}
    unexpected = sorted(set(outputs) - expected_names)
    if unexpected:
        raise PluginReleaseNodeError(
            f"Plugin invoker returned unexpected outputs: {', '.join(unexpected)}"
        )
    values: dict[str, object] = {}
    for port in contract.outputs:
        value = outputs.get(port.name)
        if value is None:
            if port.required:
                raise PluginReleaseNodeError(
                    f"Plugin invoker returned no output for required port {port.name!r}"
                )
            continue
        produces = _artifact_type_key_of(port, artifact_type_bindings)
        if isinstance(value, ArtifactRefSequence):
            if (
                port.shape != "many"
                or value.artifact_type != produces.id
                or value.schema_version != produces.schema_version
            ):
                raise PluginReleaseNodeError(
                    f"Plugin output {port.name!r} expected "
                    f"{produces.id}@{produces.schema_version}, got "
                    f"{value.artifact_type}@{value.schema_version}"
                )
        elif value.key() != produces or port.shape == "many":
            raise PluginReleaseNodeError(
                f"Plugin output {port.name!r} expected "
                f"{produces.id}@{produces.schema_version}, got "
                f"{value.artifact_type}@{value.schema_version}"
            )
        values[port.name] = value
    return values


def _artifact_type_key_of(
    port: PluginPortContract,
    artifact_type_bindings: Mapping[str, ArtifactTypeKey],
) -> ArtifactTypeKey:
    if port.artifact_type is not None:
        return ArtifactTypeKey(
            port.artifact_type.id,
            port.artifact_type.schema_version,
        )
    variable = port.artifact_type_variable
    if variable is None or variable not in artifact_type_bindings:
        raise PluginReleaseNodeError(
            f"Plugin port {port.name!r} kept an unresolved artifact type variable"
        )
    return artifact_type_bindings[variable]


def _accepts_of(
    port: PluginPortContract,
    artifact_type_bindings: Mapping[str, ArtifactTypeKey],
) -> ArtifactTypeKey | ArtifactTypeVariable:
    if port.artifact_type is not None:
        return ArtifactTypeKey(
            port.artifact_type.id,
            port.artifact_type.schema_version,
        )
    variable = port.artifact_type_variable or ""
    return artifact_type_bindings.get(variable, ArtifactTypeVariable(variable))


def _input_model_for(
    contract: PluginNodeContract,
    artifact_type_bindings: Mapping[str, ArtifactTypeKey],
) -> type[NodeInput]:
    fields: dict[str, tuple[object, object]] = {}
    for port in contract.inputs:
        accepts = _accepts_of(port, artifact_type_bindings)
        description = port.description
        if port.instance_plugs:
            annotation = list[ArtifactRef | ArtifactRefSequence]
            meta = InPort(accepts, variadic=True, instance_plugs=True)
        elif port.variadic:
            item_annotation = (
                ArtifactRefSequence if port.shape == "many" else ArtifactRef
            )
            annotation = list[item_annotation]  # type: ignore[valid-type]
            meta = InPort(accepts, variadic=True)
        elif port.shape == "many":
            annotation = ArtifactRefSequence
            meta = InPort(accepts)
        else:
            annotation = ArtifactRef
            meta = InPort(accepts)
        if port.required:
            fields[port.name] = (
                Annotated[annotation, meta],  # type: ignore[valid-type]
                Field(description=description),
            )
        else:
            optional_annotation = annotation | None  # type: ignore[operator]
            fields[port.name] = (
                Annotated[optional_annotation, meta],  # type: ignore[valid-type]
                Field(default=None, description=description),
            )
    model = create_model(
        "PluginReleaseNodeInput",
        __base__=NodeInput,
        **cast("dict[str, Any]", fields),
    )
    return model


def _output_model_for(
    contract: PluginNodeContract,
    artifact_type_bindings: Mapping[str, ArtifactTypeKey],
) -> type[NodeOutput]:
    fields: dict[str, tuple[object, object]] = {}
    for port in contract.outputs:
        produces = _accepts_of(port, artifact_type_bindings)
        description = port.description
        annotation = ArtifactRefSequence if port.shape == "many" else ArtifactRef
        if port.required:
            fields[port.name] = (
                Annotated[annotation, OutPort(produces)],
                Field(description=description),
            )
        else:
            fields[port.name] = (
                Annotated[annotation | None, OutPort(produces)],
                Field(default=None, description=description),
            )
    model = create_model(
        "PluginReleaseNodeOutput",
        __base__=NodeOutput,
        **cast("dict[str, Any]", fields),
    )
    return model


__all__ = [
    "PluginInvocationError",
    "PluginInvocationRequest",
    "PluginInvocationResult",
    "PluginInvoker",
    "PluginReleaseNodeConfig",
    "PluginReleaseNode",
    "PluginReleaseNodeError",
]
