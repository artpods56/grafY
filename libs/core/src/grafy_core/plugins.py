from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from inspect import Parameter, getdoc, iscoroutinefunction, signature
from pathlib import Path
import re
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Protocol,
    TypeAlias,
    cast,
    get_type_hints,
    override,
)

from grafy_core.artifacts import (
    ArtifactFieldProjection,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    MaterializedJsonType,
    NodeConfig,
    NodeInput,
    NodeOutput,
    Artifact,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.conversions import (
    ArtifactConversion,
    ArtifactConversionKey,
    conversion_runtime_types_are_compatible,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.modules import (
    MODULE_BOUNDARY_OPERATOR_VERSION,
    MODULE_INPUT_OPERATOR_ID,
    MODULE_OUTPUT_OPERATOR_ID,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    ConfigContract,
    Node,
    NodeExecutionContext,
    derive_input_contract,
    derive_output_contract,
)
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    UnavailableNodeSecretResolver,
)
from grafy_core.ports.staged_uploads import StagedUploadRepositoryPort
from grafy_core.ports.storage import FileStoragePort

if TYPE_CHECKING:
    from grafy_core.runtime.persistence import ArtifactOutputWriter
    from grafy_core.runtime.resolvers import Resolver


_MAX_PROJECTION_SCHEMA_DEPTH: Final = 32
_MAX_FIELD_PROJECTIONS: Final = 1024


class NodeCachePolicy(StrEnum):
    NEVER = "never"
    EXACT = "exact"


class PluginUnitOfWorkPort(UnitOfWorkPort, Protocol):
    """Workbench UoW surface available to plugin factories at runtime."""

    @property
    def staged_uploads(self) -> StagedUploadRepositoryPort: ...


@dataclass(frozen=True, slots=True)
class PluginRuntimeContext:
    workspace: Path
    uploads_dir: Path
    storage: FileStoragePort
    uow: PluginUnitOfWorkPort
    bucket: str
    storage_backend: str = "local"
    node_secrets: NodeSecretResolverPort = field(
        default_factory=UnavailableNodeSecretResolver
    )


@dataclass(frozen=True, slots=True)
class NodeSecretInput:
    name: str
    title: str
    config_dependencies: tuple[str, ...] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]*", self.name) is None:
            raise ValueError(
                "Node secret input name must start with a lowercase letter and "
                "contain only lowercase letters, digits, and underscores"
            )
        if len(self.name) > 255:
            raise ValueError("Node secret input name must be at most 255 characters")
        if self.title.strip() == "":
            raise ValueError("Node secret input title must not be blank")
        if len(self.config_dependencies) != len(set(self.config_dependencies)):
            raise ValueError(
                f"Node secret input {self.name!r} dependencies must be unique"
            )
        for dependency in self.config_dependencies:
            if dependency.strip() == "" or dependency != dependency.strip():
                raise ValueError(
                    f"Node secret input {self.name!r} dependency names must be "
                    "non-empty without surrounding whitespace"
                )


@dataclass(frozen=True, slots=True)
class NodeStagedUploadInput:
    """One config field whose upload keys the host authorizes and stages."""

    config_field: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]*", self.config_field) is None:
            raise ValueError(
                "Node staged-upload config field must start with a lowercase letter "
                "and contain only lowercase letters, digits, and underscores"
            )
        if len(self.config_field) > 255:
            raise ValueError(
                "Node staged-upload config field must be at most 255 characters"
            )


MAX_NODE_HTTP_EGRESS_CONFIGURED_FIELDS: Final = 8


@dataclass(frozen=True, slots=True)
class NodeHttpEgressInput:
    """One config field whose value may become a broker-mediated HTTP origin."""

    config_field: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_]*", self.config_field) is None:
            raise ValueError(
                "Node HTTP egress config field must start with a lowercase letter "
                "and contain only lowercase letters, digits, and underscores"
            )
        if len(self.config_field) > 255:
            raise ValueError(
                "Node HTTP egress config field must be at most 255 characters"
            )


@dataclass(frozen=True, slots=True)
class NodeHttpEgressContract:
    """The destination sources one node declares for ``network.egress``.

    Declaring authority is not granting authority: the deployment's assigned
    network access profile still bounds every origin before a sandbox starts.
    """

    configured_inputs: tuple[NodeHttpEgressInput, ...] = ()
    dynamic_destinations: bool = False


NodeFactory: TypeAlias = Callable[
    [PluginRuntimeContext],
    Node[Any, Any, Any],
]
type LegacyNodeFunction[
    ConfigT: NodeConfig,
    InputT: NodeInput,
    OutputT: NodeOutput,
] = Callable[[ConfigT, InputT], Awaitable[OutputT]]
type ContextNodeFunction[
    ConfigT: NodeConfig,
    InputT: NodeInput,
    OutputT: NodeOutput,
] = Callable[[NodeExecutionContext, ConfigT, InputT], Awaitable[OutputT]]
type NodeFunction[ConfigT: NodeConfig, InputT: NodeInput, OutputT: NodeOutput] = (
    LegacyNodeFunction[ConfigT, InputT, OutputT]
    | ContextNodeFunction[ConfigT, InputT, OutputT]
)
ResolverFactory: TypeAlias = Callable[
    [PluginRuntimeContext],
    "Resolver[object]",
]
WriterFactory: TypeAlias = Callable[
    [PluginRuntimeContext],
    "ArtifactOutputWriter",
]


@dataclass(frozen=True, slots=True)
class NodeRegistration:
    node_class: type[Node[Any, Any, Any]]
    factory: NodeFactory | None
    secret_inputs: tuple[NodeSecretInput, ...] = ()
    staged_upload_inputs: tuple[NodeStagedUploadInput, ...] = ()
    http_egress: NodeHttpEgressContract | None = None
    required_capabilities: tuple[PluginRuntimeCapability, ...] = ()
    cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER

    @property
    def plugin_slug(self) -> str:
        return self.node_class.plugin_slug

    @property
    def title(self) -> str:
        return self.node_class.title

    @property
    def description(self) -> str:
        return self.node_class.description

    @property
    def key(self) -> tuple[str, int]:
        return (
            self.node_class.operator_id,
            self.node_class.operator_version,
        )


class PluginRegistrationError(RuntimeError):
    pass


class UnknownOperatorError(LookupError):
    pass


class Plugin:
    def __init__(
        self,
        *,
        slug: str,
        title: str,
        capabilities: tuple[PluginRuntimeCapability, ...] = (),
    ) -> None:
        if slug.strip() == "":
            raise PluginRegistrationError("Plugin slug must not be empty")
        if title.strip() == "":
            raise PluginRegistrationError(f"Plugin {slug!r} title must not be empty")
        self.slug = slug
        self.title = title
        self.capabilities = tuple(
            PluginRuntimeCapability(value) for value in capabilities
        )
        self._nodes: dict[tuple[str, int], NodeRegistration] = {}
        self._artifact_types: dict[tuple[str, int], ArtifactTypeSpec] = {}
        self._artifact_type_dependencies: dict[tuple[str, int], ArtifactTypeSpec] = {}
        self._artifact_conversions: dict[
            ArtifactConversionKey,
            ArtifactConversion[Any, Any],
        ] = {}
        self._resolver_factories: list[ResolverFactory] = []
        self._writer_factories: list[WriterFactory] = []

    def node[NodeT: Node[Any, Any, Any]](
        self,
        *,
        operator_id: str,
        version: int,
        title: str,
        factory: NodeFactory | None = None,
        secret_inputs: tuple[NodeSecretInput, ...] = (),
        staged_upload_inputs: tuple[NodeStagedUploadInput, ...] = (),
        http_egress: NodeHttpEgressContract | None = None,
        required_capabilities: tuple[PluginRuntimeCapability, ...] = (),
        cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER,
    ) -> Callable[[type[NodeT]], type[NodeT]]:
        if operator_id.strip() == "":
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} node operator_id must not be empty"
            )
        if version < 1:
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} node {operator_id!r} version must be positive"
            )
        if title.strip() == "":
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} node {operator_id!r} title must not be empty"
            )

        def decorate(node_class: type[NodeT]) -> type[NodeT]:
            key = (operator_id, version)
            if key in self._nodes:
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} already declares operator "
                    f"{operator_id}@{version}"
                )
            node_class.operator_id = operator_id
            node_class.operator_version = version
            node_class.plugin_slug = self.slug
            node_class.title = title
            node_class.description = getdoc(node_class) or ""
            secret_names = [secret_input.name for secret_input in secret_inputs]
            if len(secret_names) != len(set(secret_names)):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} declares duplicate "
                    "secret input names"
                )
            config_fields = node_class.config_contract.model.model_fields
            for secret_input in secret_inputs:
                missing_dependencies = sorted(
                    set(secret_input.config_dependencies) - set(config_fields)
                )
                if not missing_dependencies:
                    continue
                rendered = ", ".join(missing_dependencies)
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} secret input "
                    f"{secret_input.name!r} references missing config fields: "
                    f"{rendered}"
                )
            staged_upload_fields = [
                staged_upload.config_field for staged_upload in staged_upload_inputs
            ]
            if len(staged_upload_fields) != len(set(staged_upload_fields)):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} declares duplicate "
                    "staged-upload config fields"
                )
            missing_staged_upload_fields = sorted(
                set(staged_upload_fields) - set(config_fields)
            )
            if missing_staged_upload_fields:
                rendered = ", ".join(missing_staged_upload_fields)
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} staged-upload "
                    f"inputs reference missing config fields: {rendered}"
                )
            if http_egress is not None:
                http_egress_fields = [
                    configured_input.config_field
                    for configured_input in http_egress.configured_inputs
                ]
                if len(http_egress_fields) != len(set(http_egress_fields)):
                    raise PluginRegistrationError(
                        f"Plugin {self.slug!r} node {operator_id!r} declares "
                        "duplicate HTTP egress config fields"
                    )
                if len(http_egress_fields) > MAX_NODE_HTTP_EGRESS_CONFIGURED_FIELDS:
                    raise PluginRegistrationError(
                        f"Plugin {self.slug!r} node {operator_id!r} declares more "
                        f"than {MAX_NODE_HTTP_EGRESS_CONFIGURED_FIELDS} HTTP egress "
                        "config fields"
                    )
                missing_http_egress_fields = sorted(
                    set(http_egress_fields) - set(config_fields)
                )
                if missing_http_egress_fields:
                    rendered = ", ".join(missing_http_egress_fields)
                    raise PluginRegistrationError(
                        f"Plugin {self.slug!r} node {operator_id!r} HTTP egress "
                        f"inputs reference missing config fields: {rendered}"
                    )
            normalized_capabilities = tuple(
                sorted(
                    {
                        PluginRuntimeCapability(capability)
                        for capability in required_capabilities
                    },
                    key=lambda capability: capability.value,
                )
            )
            if (
                secret_inputs
                and PluginRuntimeCapability.NODE_SECRETS not in normalized_capabilities
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} declares secret "
                    "inputs without requiring node.secrets"
                )
            if (
                staged_upload_inputs
                and PluginRuntimeCapability.STAGED_UPLOADS
                not in normalized_capabilities
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} declares staged "
                    "uploads without requiring staged.uploads"
                )
            if (
                http_egress is not None
                and PluginRuntimeCapability.NETWORK_EGRESS
                not in normalized_capabilities
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} node {operator_id!r} declares HTTP "
                    "egress without requiring network.egress"
                )
            registered_class: type[Node[Any, Any, Any]] = node_class
            registration = NodeRegistration(
                node_class=registered_class,
                factory=factory,
                secret_inputs=secret_inputs,
                staged_upload_inputs=staged_upload_inputs,
                http_egress=http_egress,
                required_capabilities=normalized_capabilities,
                cache_policy=cache_policy,
            )
            self._nodes[key] = registration
            return node_class

        return decorate

    def function_node[
        ConfigT: NodeConfig,
        InputT: NodeInput,
        OutputT: NodeOutput,
    ](
        self,
        *,
        operator_id: str,
        version: int,
        title: str,
        http_egress: NodeHttpEgressContract | None = None,
        required_capabilities: tuple[PluginRuntimeCapability, ...] = (),
        cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER,
    ) -> Callable[
        [NodeFunction[ConfigT, InputT, OutputT]],
        NodeFunction[ConfigT, InputT, OutputT],
    ]:
        """Register one stateless async function as a node."""

        def decorate(
            function: NodeFunction[ConfigT, InputT, OutputT],
        ) -> NodeFunction[ConfigT, InputT, OutputT]:
            if not iscoroutinefunction(function):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} must be async"
                )
            function_signature = signature(function)
            parameters = list(function_signature.parameters.values())
            if len(parameters) not in {2, 3} or any(
                parameter.kind
                not in {Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
                for parameter in parameters
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} must declare "
                    "either (config, inputs) or (context, config, inputs) "
                    "positional parameters"
                )
            try:
                hints = get_type_hints(function)
            except Exception as exc:
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} has "
                    "unresolvable type annotations"
                ) from exc
            accepts_context = len(parameters) == 3
            config_parameter_index = 1 if accepts_context else 0
            input_parameter_index = 2 if accepts_context else 1
            if (
                accepts_context
                and hints.get(parameters[0].name) is not NodeExecutionContext
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} context "
                    "parameter must be annotated with NodeExecutionContext"
                )
            config_model = hints.get(parameters[config_parameter_index].name)
            input_model = hints.get(parameters[input_parameter_index].name)
            output_model = hints.get("return")
            if not isinstance(config_model, type) or not issubclass(
                config_model, NodeConfig
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} config "
                    "parameter must be annotated with a NodeConfig model"
                )
            if not isinstance(input_model, type) or not issubclass(
                input_model, NodeInput
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} inputs "
                    "parameter must be annotated with a NodeInput model"
                )
            if not isinstance(output_model, type) or not issubclass(
                output_model, NodeOutput
            ):
                raise PluginRegistrationError(
                    f"Plugin {self.slug!r} function node {operator_id!r} return "
                    "type must be a NodeOutput model"
                )

            legacy_function = cast(
                Callable[[NodeConfig, NodeInput], Awaitable[NodeOutput]],
                function,
            )
            context_function = cast(
                Callable[
                    [NodeExecutionContext, NodeConfig, NodeInput],
                    Awaitable[NodeOutput],
                ],
                function,
            )

            class FunctionNodeAdapter(Node[NodeConfig, NodeInput, NodeOutput]):
                @override
                async def run(
                    self,
                    context: NodeExecutionContext,
                    config: NodeConfig,
                    inputs: NodeInput,
                    /,
                ) -> NodeOutput:
                    if accepts_context:
                        return await context_function(context, config, inputs)
                    return await legacy_function(config, inputs)

            FunctionNodeAdapter.__name__ = function.__name__
            FunctionNodeAdapter.__qualname__ = function.__qualname__
            FunctionNodeAdapter.__doc__ = getdoc(function)
            FunctionNodeAdapter.config_contract = ConfigContract(model=config_model)
            FunctionNodeAdapter.input_contract = derive_input_contract(input_model)
            FunctionNodeAdapter.output_contract = derive_output_contract(output_model)
            self.node(
                operator_id=operator_id,
                version=version,
                title=title,
                http_egress=http_egress,
                required_capabilities=required_capabilities,
                cache_policy=cache_policy,
            )(FunctionNodeAdapter)
            return function

        return decorate

    def register_artifact_type(self, artifact_type: ArtifactTypeSpec) -> None:
        key = (
            artifact_type.key.id,
            artifact_type.key.schema_version,
        )
        if key in self._artifact_type_dependencies:
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} cannot both own and depend on artifact type "
                f"{key[0]}@{key[1]}"
            )
        if key in self._artifact_types:
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} already declares artifact type {key[0]}@{key[1]}"
            )
        self._artifact_types[key] = artifact_type

    def register_artifact_type_dependency(
        self,
        artifact_type: ArtifactTypeSpec,
    ) -> None:
        key = (
            artifact_type.key.id,
            artifact_type.key.schema_version,
        )
        if key in self._artifact_types:
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} cannot both own and depend on artifact type "
                f"{key[0]}@{key[1]}"
            )
        existing = self._artifact_type_dependencies.get(key)
        if existing == artifact_type:
            return
        if existing is not None:
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} declares different exact contracts for "
                f"artifact type dependency {key[0]}@{key[1]}"
            )
        self._artifact_type_dependencies[key] = artifact_type

    def register_artifact_conversion[SourceT, TargetT](
        self,
        conversion: ArtifactConversion[SourceT, TargetT],
    ) -> None:
        if conversion.key in self._artifact_conversions:
            raise PluginRegistrationError(
                f"Plugin {self.slug!r} already declares artifact conversion "
                f"{conversion.key.id}@{conversion.key.version}"
            )
        self._artifact_conversions[conversion.key] = conversion

    def register_resolver(self, factory: ResolverFactory) -> None:
        self._resolver_factories.append(factory)

    def register_writer(self, factory: WriterFactory) -> None:
        self._writer_factories.append(factory)

    def register(self, artifact: Artifact) -> None:
        self.register_artifact_type(artifact.spec)
        self._writer_factories.append(artifact.writer)
        self._resolver_factories.append(artifact.resolver)

    @property
    def nodes(self) -> tuple[NodeRegistration, ...]:
        return tuple(self._nodes.values())

    @property
    def artifact_types(self) -> tuple[ArtifactTypeSpec, ...]:
        return tuple(self._artifact_types.values())

    @property
    def artifact_type_dependencies(self) -> tuple[ArtifactTypeSpec, ...]:
        return tuple(self._artifact_type_dependencies.values())

    @property
    def artifact_conversions(self) -> tuple[ArtifactConversion[Any, Any], ...]:
        return tuple(self._artifact_conversions.values())

    @property
    def resolver_factories(self) -> tuple[ResolverFactory, ...]:
        return tuple(self._resolver_factories)

    @property
    def writer_factories(self) -> tuple[WriterFactory, ...]:
        return tuple(self._writer_factories)


@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    slug: str
    title: str


@dataclass(frozen=True, slots=True)
class _InstalledPluginDeclaration:
    plugin: InstalledPlugin
    nodes: tuple[NodeRegistration, ...]
    artifact_types: tuple[ArtifactTypeSpec, ...]
    artifact_type_dependencies: tuple[ArtifactTypeSpec, ...]
    artifact_conversions: tuple[ArtifactConversion[Any, Any], ...]
    resolver_factories: tuple[ResolverFactory, ...]
    writer_factories: tuple[WriterFactory, ...]


class PluginRegistry:
    def __init__(self) -> None:
        self._declarations: dict[str, _InstalledPluginDeclaration] = {}
        self._nodes: dict[tuple[str, int], NodeRegistration] = {}
        self._artifact_types: dict[tuple[str, int], ArtifactTypeSpec] = {}
        self._artifact_type_owners: dict[tuple[str, int], str] = {}
        self._artifact_conversions: dict[
            ArtifactConversionKey,
            ArtifactConversion[Any, Any],
        ] = {}
        self._artifact_conversion_owners: dict[ArtifactConversionKey, str] = {}
        self._frozen = False

    def install(
        self,
        plugin: Plugin,
    ) -> None:
        if self._frozen:
            raise PluginRegistrationError("Plugin registry is frozen")
        if plugin.slug in self._declarations:
            raise PluginRegistrationError(
                f"Plugin slug {plugin.slug!r} is already installed"
            )

        declaration = _InstalledPluginDeclaration(
            plugin=InstalledPlugin(slug=plugin.slug, title=plugin.title),
            nodes=plugin.nodes,
            artifact_types=plugin.artifact_types,
            artifact_type_dependencies=plugin.artifact_type_dependencies,
            artifact_conversions=plugin.artifact_conversions,
            resolver_factories=plugin.resolver_factories,
            writer_factories=plugin.writer_factories,
        )

        duplicate_nodes = [
            registration.key
            for registration in declaration.nodes
            if registration.key in self._nodes
        ]
        if duplicate_nodes:
            operator_id, version = duplicate_nodes[0]
            owner = self._nodes[(operator_id, version)].plugin_slug
            raise PluginRegistrationError(
                f"Plugin {plugin.slug!r} operator {operator_id}@{version} "
                f"conflicts with plugin {owner!r}"
            )

        duplicate_artifacts = [
            (artifact_type.key.id, artifact_type.key.schema_version)
            for artifact_type in declaration.artifact_types
            if (
                artifact_type.key.id,
                artifact_type.key.schema_version,
            )
            in self._artifact_types
        ]
        if duplicate_artifacts:
            artifact_id, schema_version = duplicate_artifacts[0]
            raise PluginRegistrationError(
                f"Plugin {plugin.slug!r} artifact type "
                f"{artifact_id}@{schema_version} is already installed"
            )

        duplicate_conversions = [
            conversion.key
            for conversion in declaration.artifact_conversions
            if conversion.key in self._artifact_conversions
        ]
        if duplicate_conversions:
            conversion_key = duplicate_conversions[0]
            raise PluginRegistrationError(
                f"Plugin {plugin.slug!r} artifact conversion "
                f"{conversion_key.id}@{conversion_key.version} is already installed"
            )

        self._declarations[plugin.slug] = declaration
        for registration in declaration.nodes:
            self._nodes[registration.key] = registration
        for artifact_type in declaration.artifact_types:
            key = (
                artifact_type.key.id,
                artifact_type.key.schema_version,
            )
            self._artifact_types[key] = artifact_type
            self._artifact_type_owners[key] = plugin.slug
        for conversion in declaration.artifact_conversions:
            self._artifact_conversions[conversion.key] = conversion
            self._artifact_conversion_owners[conversion.key] = plugin.slug

    def register_module_boundaries(
        self,
        registrations: tuple[NodeRegistration, NodeRegistration],
    ) -> None:
        """Register the host-owned Module input/output execution boundaries."""

        if self._frozen:
            raise PluginRegistrationError("Plugin registry is frozen")
        expected_keys = {
            (MODULE_INPUT_OPERATOR_ID, MODULE_BOUNDARY_OPERATOR_VERSION),
            (MODULE_OUTPUT_OPERATOR_ID, MODULE_BOUNDARY_OPERATOR_VERSION),
        }
        observed_keys = {registration.key for registration in registrations}
        if observed_keys != expected_keys:
            raise PluginRegistrationError(
                "Module boundary registrations must contain module.input@1 and "
                "module.output@1"
            )
        duplicate_nodes = [
            registration.key
            for registration in registrations
            if registration.key in self._nodes
        ]
        if duplicate_nodes:
            operator_id, version = duplicate_nodes[0]
            owner = self._nodes[(operator_id, version)].plugin_slug
            raise PluginRegistrationError(
                f"Module boundary {operator_id}@{version} conflicts with "
                f"plugin {owner!r}"
            )
        for registration in registrations:
            self._nodes[registration.key] = registration

    def freeze(self) -> None:
        artifact_contracts_by_key: dict[
            ArtifactTypeKey, tuple[ArtifactTypeSpec, str]
        ] = {
            artifact_type.key: (artifact_type, plugin_slug)
            for plugin_slug, declaration in self._declarations.items()
            for artifact_type in declaration.artifact_types
        }
        for plugin_slug, declaration in self._declarations.items():
            for dependency in declaration.artifact_type_dependencies:
                existing = artifact_contracts_by_key.get(dependency.key)
                if existing is None:
                    artifact_contracts_by_key[dependency.key] = (
                        dependency,
                        plugin_slug,
                    )
                    continue
                existing_contract, existing_plugin_slug = existing
                if existing_contract == dependency:
                    continue
                raise PluginRegistrationError(
                    f"Plugins {existing_plugin_slug!r} and {plugin_slug!r} declare "
                    "different exact contracts for artifact type "
                    f"{dependency.key.id}@{dependency.key.schema_version}"
                )

        for registration in self._nodes.values():
            declaration = self._declarations.get(registration.plugin_slug)
            declared_artifact_keys: set[ArtifactTypeKey] = (
                set()
                if declaration is None
                else {
                    artifact_type.key
                    for artifact_type in (
                        *declaration.artifact_types,
                        *declaration.artifact_type_dependencies,
                    )
                }
            )
            port_contracts = [
                ("input", port.name, port.accepts)
                for port in registration.node_class.input_contract.ports.values()
            ]
            port_contracts.extend(
                ("output", port.name, port.produces)
                for port in registration.node_class.output_contract.ports.values()
            )
            for direction, port_name, artifact_type in port_contracts:
                if isinstance(artifact_type, ArtifactTypeVariable):
                    continue
                if artifact_type in declared_artifact_keys:
                    continue
                raise PluginRegistrationError(
                    f"Plugin {registration.plugin_slug!r} operator "
                    f"{registration.key[0]}@{registration.key[1]} {direction} "
                    f"port {port_name!r} references artifact type "
                    f"{artifact_type.id}@{artifact_type.schema_version}, which is "
                    "neither owned nor declared as an exact dependency"
                )

        conversions = tuple(self._artifact_conversions.values())
        for plugin_slug, declaration in self._declarations.items():
            declared_artifact_keys = {
                artifact_type.key
                for artifact_type in (
                    *declaration.artifact_types,
                    *declaration.artifact_type_dependencies,
                )
            }
            for conversion in declaration.artifact_conversions:
                endpoints = (
                    ("source", conversion.source),
                    ("target", conversion.target),
                )
                for endpoint_name, artifact_type in endpoints:
                    if artifact_type in declared_artifact_keys:
                        continue
                    raise PluginRegistrationError(
                        f"Plugin {plugin_slug!r} artifact conversion "
                        f"{conversion.key.id}@{conversion.key.version} references "
                        f"{endpoint_name} artifact type {artifact_type.id}@"
                        f"{artifact_type.schema_version}, which is neither owned "
                        "nor declared as an exact dependency"
                    )

        conversions_by_source: dict[
            ArtifactTypeKey,
            list[ArtifactConversion[Any, Any]],
        ] = {}
        for conversion in conversions:
            conversions_by_source.setdefault(conversion.source, []).append(conversion)
        for preceding in conversions:
            for following in conversions_by_source.get(preceding.target, []):
                if conversion_runtime_types_are_compatible(
                    preceding.target_type,
                    following.source_type,
                ):
                    continue
                raise PluginRegistrationError(
                    f"Artifact conversions {preceding.key.id}@"
                    f"{preceding.key.version} and {following.key.id}@"
                    f"{following.key.version} meet at {preceding.target.id}@"
                    f"{preceding.target.schema_version} but have incompatible "
                    f"runtime types: {preceding.target_type} cannot feed "
                    f"{following.source_type}"
                )

        artifact_types_by_key = {
            key: contract
            for key, (contract, _plugin_slug) in artifact_contracts_by_key.items()
        }
        for plugin_slug, declaration in self._declarations.items():
            declared_artifact_keys = {
                artifact_type.key
                for artifact_type in (
                    *declaration.artifact_types,
                    *declaration.artifact_type_dependencies,
                )
            }
            for artifact_type in (
                *declaration.artifact_types,
                *declaration.artifact_type_dependencies,
            ):
                declared_paths: set[tuple[str, ...]] = set()
                for projection in artifact_type.field_projections:
                    if not projection.path:
                        raise PluginRegistrationError(
                            f"Artifact type {artifact_type.key.id}@"
                            f"{artifact_type.key.schema_version} declares a field "
                            "projection with an empty path"
                        )
                    rendered_path = ".".join(projection.path)
                    if projection.path in declared_paths:
                        raise PluginRegistrationError(
                            f"Artifact type {artifact_type.key.id}@"
                            f"{artifact_type.key.schema_version} declares duplicate "
                            f"field projection path {rendered_path!r}"
                        )
                    declared_paths.add(projection.path)
                    if projection.target not in declared_artifact_keys:
                        raise PluginRegistrationError(
                            f"Plugin {plugin_slug!r} artifact type "
                            f"{artifact_type.key.id}@"
                            f"{artifact_type.key.schema_version} field projection "
                            f"{rendered_path!r} targets artifact type "
                            f"{projection.target.id}@"
                            f"{projection.target.schema_version}, which is neither "
                            "owned nor declared as an exact dependency"
                        )

        scalar_targets: dict[MaterializedJsonType, ArtifactTypeKey] = {}
        for artifact_type in artifact_types_by_key.values():
            materialized_json_type = artifact_type.materialized_json_type
            if materialized_json_type is None:
                continue
            existing_target = scalar_targets.get(materialized_json_type)
            if existing_target is not None:
                raise PluginRegistrationError(
                    f"Artifact types {existing_target.id}@"
                    f"{existing_target.schema_version} and {artifact_type.key.id}@"
                    f"{artifact_type.key.schema_version} both declare the canonical "
                    f"JSON Schema {materialized_json_type!r} scalar target"
                )
            scalar_targets[materialized_json_type] = artifact_type.key

        expanded_artifact_types: dict[tuple[str, int], ArtifactTypeSpec] = {}
        for key, artifact_type in self._artifact_types.items():
            projections = _expanded_field_projections(
                artifact_type,
                scalar_targets,
                artifact_types_by_key,
                derive_automatic=artifact_type.materialized_json_type is None,
            )
            expanded_artifact_types[key] = replace(
                artifact_type,
                field_projections=projections,
            )

        self._artifact_types = expanded_artifact_types
        self._frozen = True

    @property
    def plugins(self) -> tuple[InstalledPlugin, ...]:
        return tuple(declaration.plugin for declaration in self._declarations.values())

    @property
    def nodes(self) -> tuple[NodeRegistration, ...]:
        return tuple(self._nodes.values())

    @property
    def artifact_types(self) -> tuple[ArtifactTypeSpec, ...]:
        return tuple(self._artifact_types.values())

    @property
    def declared_artifact_types(self) -> tuple[ArtifactTypeSpec, ...]:
        """Artifact contracts as declared before registry projection expansion."""

        return tuple(
            artifact_type
            for declaration in self._declarations.values()
            for artifact_type in declaration.artifact_types
        )

    @property
    def artifact_type_dependencies(self) -> tuple[ArtifactTypeSpec, ...]:
        dependencies_by_key: dict[ArtifactTypeKey, ArtifactTypeSpec] = {}
        for declaration in self._declarations.values():
            for dependency in declaration.artifact_type_dependencies:
                dependencies_by_key.setdefault(dependency.key, dependency)
        return tuple(dependencies_by_key.values())

    @property
    def artifact_conversions(self) -> tuple[ArtifactConversion[Any, Any], ...]:
        return tuple(self._artifact_conversions.values())

    def artifact_type_owner(self, artifact_type: ArtifactTypeKey) -> str | None:
        return self._artifact_type_owners.get(
            (artifact_type.id, artifact_type.schema_version)
        )

    def artifact_conversion_owner(self, key: ArtifactConversionKey) -> str | None:
        return self._artifact_conversion_owners.get(key)

    def node_registration(
        self,
        operator_id: str,
        operator_version: int,
    ) -> NodeRegistration:
        registration = self._nodes.get((operator_id, operator_version))
        if registration is None:
            raise UnknownOperatorError(
                f"Unknown operator {operator_id!r} at version {operator_version}"
            )
        return registration

    def build_node(
        self,
        operator_id: str,
        operator_version: int,
        context: PluginRuntimeContext,
    ) -> Node[Any, Any, Any]:
        registration = self.node_registration(operator_id, operator_version)
        if registration.factory is not None:
            return registration.factory(context)
        node_class = registration.node_class
        try:
            return node_class()
        except TypeError as exc:
            raise PluginRegistrationError(
                f"Plugin {registration.plugin_slug!r} operator "
                f"{operator_id}@{operator_version} requires an explicit node factory"
            ) from exc

    def build_resolvers(
        self,
        context: PluginRuntimeContext,
    ) -> tuple["Resolver[object]", ...]:
        return tuple(
            factory(context)
            for declaration in self._declarations.values()
            for factory in declaration.resolver_factories
        )

    def build_writers(
        self,
        context: PluginRuntimeContext,
    ) -> tuple["ArtifactOutputWriter", ...]:
        return tuple(
            factory(context)
            for declaration in self._declarations.values()
            for factory in declaration.writer_factories
        )


_KNOWN_JSON_SCHEMA_TYPES: Final = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)


def _expanded_field_projections(
    artifact_type: ArtifactTypeSpec,
    scalar_targets: dict[MaterializedJsonType, ArtifactTypeKey],
    artifact_types_by_key: dict[ArtifactTypeKey, ArtifactTypeSpec],
    *,
    derive_automatic: bool,
) -> tuple[ArtifactFieldProjection, ...]:
    explicit_by_path = {
        projection.path: projection for projection in artifact_type.field_projections
    }
    derived: list[ArtifactFieldProjection] = []
    stack: list[
        tuple[
            JsonObject,
            tuple[str, ...],
            tuple[str, ...],
            frozenset[str],
            int,
        ]
    ] = [(artifact_type.payload_schema, (), (), frozenset(), 0)]

    while stack:
        schema, path, ancestor_titles, active_refs, depth = stack.pop()
        if depth > _MAX_PROJECTION_SCHEMA_DEPTH:
            rendered_path = ".".join(path) or "<root>"
            raise PluginRegistrationError(
                f"Artifact type {artifact_type.key.id}@"
                f"{artifact_type.key.schema_version} payload schema exceeds the "
                f"maximum projection depth of {_MAX_PROJECTION_SCHEMA_DEPTH} at "
                f"path {rendered_path!r}"
            )

        raw_title = _schema_title(schema)
        resolved_schema = schema
        branch_refs = active_refs
        resolved_depth = depth
        while True:
            ref = resolved_schema.get("$ref")
            if not isinstance(ref, str):
                break
            if not ref.startswith("#/"):
                resolved_schema = {}
                break
            if ref in branch_refs:
                rendered_path = ".".join(path) or "<root>"
                raise PluginRegistrationError(
                    f"Artifact type {artifact_type.key.id}@"
                    f"{artifact_type.key.schema_version} payload schema contains "
                    f"cyclic local reference {ref!r} at path {rendered_path!r}"
                )
            branch_refs = branch_refs | {ref}
            resolved_depth += 1
            if resolved_depth > _MAX_PROJECTION_SCHEMA_DEPTH:
                rendered_path = ".".join(path) or "<root>"
                raise PluginRegistrationError(
                    f"Artifact type {artifact_type.key.id}@"
                    f"{artifact_type.key.schema_version} payload schema exceeds the "
                    f"maximum projection depth of {_MAX_PROJECTION_SCHEMA_DEPTH} "
                    f"while resolving {ref!r} at path {rendered_path!r}"
                )
            resolved_schema = _resolve_local_schema_ref(
                artifact_type,
                ref,
            )
            if raw_title is None:
                raw_title = _schema_title(resolved_schema)

        if not path:
            titles = ancestor_titles
        else:
            current_title = raw_title or _humanized_schema_segment(path[-1])
            titles = (*ancestor_titles, current_title)

        schema_type = resolved_schema.get("type")
        explicit_projection = explicit_by_path.get(path)
        if (
            explicit_projection is not None
            and isinstance(schema_type, str)
            and schema_type in _KNOWN_JSON_SCHEMA_TYPES
        ):
            target_spec = artifact_types_by_key[explicit_projection.target]
            target_json_type = target_spec.materialized_json_type
            if target_json_type is not None and target_json_type != schema_type:
                rendered_path = ".".join(path)
                raise PluginRegistrationError(
                    f"Artifact type {artifact_type.key.id}@"
                    f"{artifact_type.key.schema_version} field projection "
                    f"{rendered_path!r} targets {target_spec.key.id}@"
                    f"{target_spec.key.schema_version}, which materializes JSON "
                    f"Schema {target_json_type!r}, but the projected field is "
                    f"{schema_type!r}"
                )

        if schema_type == "string" or schema_type == "integer":
            materialized_schema_type = cast(MaterializedJsonType, schema_type)
            if explicit_projection is None and derive_automatic and path:
                target = scalar_targets.get(materialized_schema_type)
                if target is None:
                    continue
                derived.append(
                    ArtifactFieldProjection(
                        path=path,
                        target=target,
                        title=" · ".join(titles),
                    )
                )
                if (
                    len(artifact_type.field_projections) + len(derived)
                    > _MAX_FIELD_PROJECTIONS
                ):
                    raise PluginRegistrationError(
                        f"Artifact type {artifact_type.key.id}@"
                        f"{artifact_type.key.schema_version} payload schema expands "
                        f"beyond the maximum of {_MAX_FIELD_PROJECTIONS} field "
                        "projections"
                    )
            continue
        if schema_type == "array":
            continue

        properties = resolved_schema.get("properties")
        if not isinstance(properties, dict):
            continue
        schema_properties = cast(dict[object, object], properties)
        property_names = sorted(
            name for name in schema_properties if isinstance(name, str)
        )
        for property_name in reversed(property_names):
            property_schema = schema_properties[property_name]
            if not isinstance(property_schema, dict):
                continue
            stack.append(
                (
                    cast(JsonObject, property_schema),
                    (*path, property_name),
                    titles,
                    branch_refs,
                    resolved_depth + 1,
                )
            )

    projections = (*artifact_type.field_projections, *derived)
    if len(projections) > _MAX_FIELD_PROJECTIONS:
        raise PluginRegistrationError(
            f"Artifact type {artifact_type.key.id}@"
            f"{artifact_type.key.schema_version} declares more than the maximum "
            f"of {_MAX_FIELD_PROJECTIONS} field projections"
        )
    return tuple(sorted(projections, key=lambda projection: projection.path))


def _resolve_local_schema_ref(
    artifact_type: ArtifactTypeSpec,
    ref: str,
) -> JsonObject:
    value: object = artifact_type.payload_schema
    for raw_segment in ref[2:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict):
            raise PluginRegistrationError(
                f"Artifact type {artifact_type.key.id}@"
                f"{artifact_type.key.schema_version} payload schema contains "
                f"unresolvable local reference {ref!r}"
            )
        schema_object = cast(dict[object, object], value)
        if segment not in schema_object:
            raise PluginRegistrationError(
                f"Artifact type {artifact_type.key.id}@"
                f"{artifact_type.key.schema_version} payload schema contains "
                f"unresolvable local reference {ref!r}"
            )
        value = schema_object[segment]
    if not isinstance(value, dict):
        raise PluginRegistrationError(
            f"Artifact type {artifact_type.key.id}@"
            f"{artifact_type.key.schema_version} payload schema local reference "
            f"{ref!r} does not resolve to a schema object"
        )
    return cast(JsonObject, value)


def _schema_title(schema: JsonObject) -> str | None:
    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def _humanized_schema_segment(segment: str) -> str:
    words = segment.replace("_", " ").replace("-", " ").split()
    return " ".join(word.capitalize() for word in words) or segment
