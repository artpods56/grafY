import re
from dataclasses import dataclass, field
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, StrictStr, field_validator

from grafy_core.artifacts import ArtifactTypeKey, NodeConfig
from grafy_core.domain.saved_graphs import (
    SavedGraph,
    GraphDocument,
    GraphEdge,
    GraphNode,
    SavedGraphRevision,
)


MODULE_INPUT_OPERATOR_ID = "module.input"
MODULE_OUTPUT_OPERATOR_ID = "module.output"
MODULE_BOUNDARY_OPERATOR_VERSION = 1
MODULE_BOUNDARY_PORT = "value"
MODULE_ARTIFACT_TYPE_VARIABLE = "T"
GRAPH_MODULE_OPERATOR_PREFIX = "graph.module."


class GraphModuleDefinitionError(ValueError):
    pass


class GraphModuleReferenceError(ValueError):
    pass


class ModuleBoundaryConfig(NodeConfig):
    public_name: StrictStr = Field(
        max_length=255,
        description="Public module port name.",
    )
    description: StrictStr | None = Field(
        default=None,
        max_length=1000,
        description="Optional description shown on the public module port.",
    )

    @field_validator("public_name")
    @classmethod
    def validate_public_name(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
            raise ValueError(
                "Module public name must start with a lowercase letter and "
                "contain only lowercase letters, digits, and underscores"
            )
        if hasattr(NodeConfig, value):
            raise ValueError(
                f"Module public name {value!r} conflicts with the node model API"
            )
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is not None and value.strip() == "":
            raise ValueError("Module port description must not be blank")
        return value


class ModuleInputConfig(ModuleBoundaryConfig):
    required: bool = Field(
        default=True,
        description="Whether callers must supply this public module input.",
    )


@dataclass(frozen=True, slots=True)
class GraphModuleReference:
    graph_id: UUID
    revision: int

    operator_prefix: ClassVar[str] = GRAPH_MODULE_OPERATOR_PREFIX

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or self.revision < 1:
            raise GraphModuleReferenceError(
                "Graph module revision must be a positive integer"
            )

    @property
    def operator_id(self) -> str:
        return f"{self.operator_prefix}{self.graph_id}"

    @property
    def operator_version(self) -> int:
        return self.revision

    @property
    def operator_key(self) -> tuple[str, int]:
        return self.operator_id, self.operator_version

    @property
    def module_path_item(self) -> str:
        return f"{self.operator_id}@{self.operator_version}"

    @classmethod
    def from_operator_identity(
        cls,
        operator_id: str,
        operator_version: int,
    ) -> Self:
        if not operator_id.startswith(cls.operator_prefix):
            raise GraphModuleReferenceError(
                f"Operator {operator_id!r}@{operator_version} is not a graph "
                "module operator"
            )
        raw_graph_id = operator_id.removeprefix(cls.operator_prefix)
        try:
            graph_id = UUID(raw_graph_id)
        except ValueError as exc:
            raise GraphModuleReferenceError(
                f"Graph module operator {operator_id!r}@{operator_version} "
                "contains an invalid saved graph UUID"
            ) from exc
        if raw_graph_id != str(graph_id):
            raise GraphModuleReferenceError(
                f"Graph module operator {operator_id!r}@{operator_version} must "
                "use the canonical lowercase saved graph UUID"
            )
        try:
            return cls(graph_id=graph_id, revision=operator_version)
        except GraphModuleReferenceError as exc:
            raise GraphModuleReferenceError(
                f"Graph module operator {operator_id!r}@{operator_version} has "
                "an invalid revision"
            ) from exc

    @classmethod
    def try_from_operator_identity(
        cls,
        operator_id: str,
        operator_version: int,
    ) -> Self | None:
        if not operator_id.startswith(cls.operator_prefix):
            return None
        return cls.from_operator_identity(operator_id, operator_version)


@dataclass(frozen=True, slots=True)
class GraphModulePort:
    name: str
    artifact_type: ArtifactTypeKey
    boundary_node_id: str
    description: str | None = None
    required: bool = True


@dataclass(frozen=True, slots=True)
class GraphModuleDefinition:
    reference: GraphModuleReference
    name: str
    document: GraphDocument
    input_ports: tuple[GraphModulePort, ...] = field(init=False)
    output_ports: tuple[GraphModulePort, ...] = field(init=False)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if normalized_name == "":
            raise GraphModuleDefinitionError("Graph module name must not be blank")
        if len(normalized_name) > 160:
            raise GraphModuleDefinitionError(
                "Graph module name must be at most 160 characters"
            )

        input_ports, output_ports = self._derive_ports()
        if not output_ports:
            raise GraphModuleDefinitionError(
                f"Graph module {self.reference.graph_id} revision "
                f"{self.reference.revision} must declare at least one Module "
                "Output boundary"
            )

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "input_ports", input_ports)
        object.__setattr__(self, "output_ports", output_ports)

    @property
    def operator_id(self) -> str:
        return self.reference.operator_id

    @property
    def operator_version(self) -> int:
        return self.reference.operator_version

    @property
    def title(self) -> str:
        return self.name

    @property
    def description(self) -> str:
        return (
            f"Saved graph module {self.name!r}, pinned to revision "
            f"{self.reference.revision}."
        )

    @classmethod
    def from_saved_graph(cls, graph: SavedGraph) -> Self:
        return cls(
            reference=GraphModuleReference(
                graph_id=graph.id,
                revision=graph.revision,
            ),
            name=graph.name,
            document=graph.document,
        )

    @classmethod
    def from_saved_graph_revision(
        cls,
        revision: SavedGraphRevision,
    ) -> Self:
        return cls(
            reference=GraphModuleReference(
                graph_id=revision.graph_id,
                revision=revision.revision,
            ),
            name=revision.name,
            document=revision.document,
        )

    def input_port(self, name: str) -> GraphModulePort:
        for port in self.input_ports:
            if port.name == name:
                return port
        raise GraphModuleDefinitionError(
            f"Graph module {self.operator_id}@{self.operator_version} has no "
            f"public input {name!r}"
        )

    def output_port(self, name: str) -> GraphModulePort:
        for port in self.output_ports:
            if port.name == name:
                return port
        raise GraphModuleDefinitionError(
            f"Graph module {self.operator_id}@{self.operator_version} has no "
            f"public output {name!r}"
        )

    def _derive_ports(
        self,
    ) -> tuple[tuple[GraphModulePort, ...], tuple[GraphModulePort, ...]]:
        input_ports: list[GraphModulePort] = []
        output_ports: list[GraphModulePort] = []
        incoming_edges: dict[str, list[GraphEdge]] = {}
        outgoing_edges: dict[str, list[GraphEdge]] = {}
        for edge in self.document.edges:
            if not edge.enabled:
                continue
            incoming_edges.setdefault(edge.to_node, []).append(edge)
            outgoing_edges.setdefault(edge.from_node, []).append(edge)

        for node in self.document.nodes:
            if node.operator_id == MODULE_INPUT_OPERATOR_ID:
                self._validate_boundary_version(node)
                config = self._validated_boundary_config(node, ModuleInputConfig)
                artifact_type = self._bound_artifact_type(node)
                node_incoming = incoming_edges.get(node.id, [])
                node_outgoing = outgoing_edges.get(node.id, [])
                if node_incoming:
                    raise self._node_error(
                        node,
                        "Module Input boundary cannot have incoming edges",
                    )
                if not node_outgoing:
                    raise self._node_error(
                        node,
                        "Module Input boundary must connect its 'value' output",
                    )
                for edge in node_outgoing:
                    if edge.from_port != MODULE_BOUNDARY_PORT:
                        raise self._node_error(
                            node,
                            f"Module Input boundary edge {edge.id!r} must start "
                            f"at output {MODULE_BOUNDARY_PORT!r}",
                        )
                    if edge.collection_mode != "direct":
                        raise self._node_error(
                            node,
                            f"Module Input boundary edge {edge.id!r} must use "
                            "direct collection mode because module ports are scalar",
                        )
                input_ports.append(
                    GraphModulePort(
                        name=config.public_name,
                        artifact_type=artifact_type,
                        boundary_node_id=node.id,
                        description=config.description,
                        required=config.required,
                    )
                )
                continue

            if node.operator_id != MODULE_OUTPUT_OPERATOR_ID:
                continue
            self._validate_boundary_version(node)
            config = self._validated_boundary_config(node, ModuleBoundaryConfig)
            artifact_type = self._bound_artifact_type(node)
            node_incoming = incoming_edges.get(node.id, [])
            node_outgoing = outgoing_edges.get(node.id, [])
            if node_outgoing:
                raise self._node_error(
                    node,
                    "Module Output boundary cannot have outgoing edges",
                )
            if len(node_incoming) != 1:
                raise self._node_error(
                    node,
                    "Module Output boundary requires exactly one incoming edge, "
                    f"got {len(node_incoming)}",
                )
            edge = node_incoming[0]
            if edge.to_port != MODULE_BOUNDARY_PORT:
                raise self._node_error(
                    node,
                    f"Module Output boundary edge {edge.id!r} must target input "
                    f"{MODULE_BOUNDARY_PORT!r}",
                )
            if edge.to_plug is not None:
                raise self._node_error(
                    node,
                    f"Module Output boundary edge {edge.id!r} cannot target an "
                    "instance plug",
                )
            if edge.collection_mode != "direct":
                raise self._node_error(
                    node,
                    f"Module Output boundary edge {edge.id!r} must use direct "
                    "collection mode because module outputs are scalar",
                )
            output_ports.append(
                GraphModulePort(
                    name=config.public_name,
                    artifact_type=artifact_type,
                    boundary_node_id=node.id,
                    description=config.description,
                )
            )

        self._validate_unique_names("input", input_ports)
        self._validate_unique_names("output", output_ports)
        return tuple(input_ports), tuple(output_ports)

    def _validate_boundary_version(self, node: GraphNode) -> None:
        if node.operator_version != MODULE_BOUNDARY_OPERATOR_VERSION:
            raise self._node_error(
                node,
                f"boundary operator version must be "
                f"{MODULE_BOUNDARY_OPERATOR_VERSION}, got {node.operator_version}",
            )
        if node.input_plugs:
            raise self._node_error(
                node,
                "boundary operators cannot declare instance input plugs",
            )

    def _validated_boundary_config[ConfigT: ModuleBoundaryConfig](
        self,
        node: GraphNode,
        config_model: type[ConfigT],
    ) -> ConfigT:
        try:
            return config_model.model_validate(node.config_dict())
        except ValueError as exc:
            raise self._node_error(node, "has invalid boundary configuration") from exc

    def _bound_artifact_type(self, node: GraphNode) -> ArtifactTypeKey:
        bindings = node.artifact_type_binding_map()
        binding_names = set(bindings)
        expected_names = {MODULE_ARTIFACT_TYPE_VARIABLE}
        missing = expected_names - binding_names
        unknown = binding_names - expected_names
        if missing:
            raise self._node_error(
                node,
                f"is missing concrete artifact type binding "
                f"{MODULE_ARTIFACT_TYPE_VARIABLE!r}",
            )
        if unknown:
            rendered = ", ".join(sorted(unknown))
            raise self._node_error(
                node,
                f"has unknown artifact type bindings: {rendered}",
            )
        return bindings[MODULE_ARTIFACT_TYPE_VARIABLE]

    def _validate_unique_names(
        self,
        direction: str,
        ports: list[GraphModulePort],
    ) -> None:
        seen: set[str] = set()
        for port in ports:
            if port.name in seen:
                raise GraphModuleDefinitionError(
                    f"Graph module {self.reference.graph_id} revision "
                    f"{self.reference.revision} declares duplicate public "
                    f"{direction} name {port.name!r}"
                )
            seen.add(port.name)

    def _node_error(
        self,
        node: GraphNode,
        message: str,
    ) -> GraphModuleDefinitionError:
        return GraphModuleDefinitionError(
            f"Graph module {self.reference.graph_id} revision "
            f"{self.reference.revision} boundary node {node.id!r} "
            f"({node.operator_id}@{node.operator_version}) {message}"
        )


__all__ = [
    "GRAPH_MODULE_OPERATOR_PREFIX",
    "GraphModuleDefinition",
    "GraphModuleDefinitionError",
    "GraphModulePort",
    "GraphModuleReference",
    "GraphModuleReferenceError",
    "MODULE_ARTIFACT_TYPE_VARIABLE",
    "MODULE_BOUNDARY_OPERATOR_VERSION",
    "MODULE_BOUNDARY_PORT",
    "MODULE_INPUT_OPERATOR_ID",
    "MODULE_OUTPUT_OPERATOR_ID",
    "ModuleBoundaryConfig",
    "ModuleInputConfig",
]
