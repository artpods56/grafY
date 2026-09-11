import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from grafy_core.artifacts import ArtifactTypeKey, NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphArtifactTypeBinding,
    SavedGraphConversion,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphInputPlug,
    SavedGraphNode,
)
from grafy_core.nodes import ArtifactTypeVariable, Node
from grafy_core.schema_contracts import validate_json_schema_value

from .models import CatalogConversion, CatalogNode, NodeCatalog


class GraphBuilderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NodeHandle:
    node_id: str
    builder_identity: object = field(repr=False, compare=False)

    def input(self, port: str) -> "InputHandle":
        return InputHandle(
            node_id=self.node_id,
            port=port,
            builder_identity=self.builder_identity,
        )

    def output(self, port: str) -> "OutputHandle":
        return OutputHandle(
            node_id=self.node_id,
            port=port,
            builder_identity=self.builder_identity,
        )


@dataclass(frozen=True, slots=True)
class InputHandle:
    node_id: str
    port: str
    builder_identity: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class OutputHandle:
    node_id: str
    port: str
    builder_identity: object = field(repr=False, compare=False)


@dataclass(slots=True)
class _AuthoredNode:
    handle: NodeHandle
    catalog_node: CatalogNode
    config: dict[str, object]
    bindings: dict[str, ArtifactTypeKey]
    input_plugs: list[SavedGraphInputPlug]
    position: GraphPoint | None


def _node_kind(catalog_node: CatalogNode) -> Literal["builtin", "plugin", "module"]:
    if catalog_node.origin in {"builtin", "plugin", "module"}:
        return catalog_node.origin
    if catalog_node.plugin_release is not None:
        return "plugin"
    if (
        catalog_node.module_graph_id is not None
        or catalog_node.plugin_slug == "graph.module"
    ):
        return "module"
    return "builtin"


def _artifact_type_variables(catalog_node: CatalogNode) -> set[str]:
    variables = {
        port.artifact_type_variable
        for port in (*catalog_node.inputs, *catalog_node.outputs)
        if port.artifact_type_variable is not None
    }
    return variables


class GraphBuilder:
    def __init__(self, catalog: NodeCatalog) -> None:
        self._catalog = catalog
        self._identity = object()
        self._nodes: list[_AuthoredNode] = []
        self._edges: list[SavedGraphEdge] = []

    def add[
        ConfigT: NodeConfig,
        InputT: NodeInput,
        OutputT: NodeOutput,
    ](
        self,
        node_class: type[Node[ConfigT, InputT, OutputT]],
        config: ConfigT,
        *,
        bindings: Mapping[str, ArtifactTypeKey] | None = None,
        position: GraphPoint | None = None,
    ) -> NodeHandle:
        matching = [
            node
            for node in self._catalog.nodes
            if node.operator_id == node_class.operator_id
            and node.operator_version == node_class.operator_version
            and node.plugin_slug == node_class.plugin_slug
        ]
        if len(matching) != 1:
            raise GraphBuilderError(
                f"Workspace catalog does not expose exactly one "
                f"{node_class.plugin_slug!r} Plugin node "
                f"{node_class.operator_id}@{node_class.operator_version}"
            )
        catalog_node = matching[0]
        if (
            catalog_node.config_schema
            != node_class.config_contract.model.model_json_schema()
        ):
            raise GraphBuilderError(
                f"Local node class {node_class.operator_id}@"
                f"{node_class.operator_version} does not match the catalog config "
                "contract"
            )
        if (
            catalog_node.input_schema
            != node_class.input_contract.model.model_json_schema()
            or catalog_node.output_schema
            != node_class.output_contract.model.model_json_schema()
        ):
            raise GraphBuilderError(
                f"Local node class {node_class.operator_id}@"
                f"{node_class.operator_version} does not match the catalog "
                "input/output schemas"
            )

        local_ports: list[tuple[object, ...]] = []
        for port in node_class.input_contract.ports.values():
            artifact_type = (
                None if isinstance(port.accepts, ArtifactTypeVariable) else port.accepts
            )
            artifact_type_variable = (
                port.accepts.name
                if isinstance(port.accepts, ArtifactTypeVariable)
                else None
            )
            local_ports.append(
                (
                    port.name,
                    "input",
                    artifact_type,
                    artifact_type_variable,
                    port.shape,
                    port.accepted_shapes,
                    port.instance_plugs,
                    port.variadic,
                    port.required,
                    port.also_accepts,
                )
            )
        for port in node_class.output_contract.ports.values():
            artifact_type = (
                None
                if isinstance(port.produces, ArtifactTypeVariable)
                else port.produces
            )
            artifact_type_variable = (
                port.produces.name
                if isinstance(port.produces, ArtifactTypeVariable)
                else None
            )
            local_ports.append(
                (
                    port.name,
                    "output",
                    artifact_type,
                    artifact_type_variable,
                    port.shape,
                    (port.shape,),
                    False,
                    False,
                    port.required,
                    (),
                )
            )
        catalog_ports = [
            (
                port.name,
                port.direction,
                port.artifact_type,
                port.artifact_type_variable,
                port.shape,
                port.accepted_shapes,
                port.instance_plugs,
                port.variadic,
                port.required,
                port.also_accepts,
            )
            for port in (*catalog_node.inputs, *catalog_node.outputs)
        ]
        if local_ports != catalog_ports:
            raise GraphBuilderError(
                f"Local node class {node_class.operator_id}@"
                f"{node_class.operator_version} does not match the catalog port "
                "contracts"
            )
        if not isinstance(config, node_class.config_contract.model):
            try:
                config = node_class.config_contract.model.model_validate(config)
            except ValidationError as exc:
                raise GraphBuilderError(
                    f"Invalid configuration for {node_class.operator_id}@"
                    f"{node_class.operator_version}: {exc}"
                ) from exc

        return self._append_node(
            catalog_node,
            config.model_dump(mode="json"),
            bindings=bindings,
            position=position,
        )

    def add_catalog_node(
        self,
        operator_id: str,
        config: Mapping[str, object],
        *,
        operator_version: int | None = None,
        plugin_slug: str | None = None,
        bindings: Mapping[str, ArtifactTypeKey] | None = None,
        position: GraphPoint | None = None,
    ) -> NodeHandle:
        matching = [
            node
            for node in self._catalog.nodes
            if node.operator_id == operator_id
            and (operator_version is None or node.operator_version == operator_version)
            and (plugin_slug is None or node.plugin_slug == plugin_slug)
        ]
        if len(matching) != 1:
            version = "" if operator_version is None else f"@{operator_version}"
            plugin = "" if plugin_slug is None else f" from Plugin {plugin_slug!r}"
            raise GraphBuilderError(
                "Workspace catalog does not expose exactly one node "
                f"{operator_id}{version}{plugin}"
            )
        catalog_node = matching[0]
        config_payload = dict(config)
        try:
            validate_json_schema_value(
                json.dumps(catalog_node.config_schema, ensure_ascii=False),
                config_payload,
            )
        except ValueError as exc:
            raise GraphBuilderError(
                f"Invalid configuration for {catalog_node.operator_id}@"
                f"{catalog_node.operator_version}: {exc}"
            ) from exc
        return self._append_node(
            catalog_node,
            config_payload,
            bindings=bindings,
            position=position,
        )

    def _append_node(
        self,
        catalog_node: CatalogNode,
        config: dict[str, object],
        *,
        bindings: Mapping[str, ArtifactTypeKey] | None,
        position: GraphPoint | None,
    ) -> NodeHandle:
        if not catalog_node.runnable:
            reason = catalog_node.non_runnable_reason or "unknown"
            detail = (
                ""
                if catalog_node.non_runnable_detail is None
                else f": {catalog_node.non_runnable_detail}"
            )
            raise GraphBuilderError(
                f"Plugin node {catalog_node.operator_id}@"
                f"{catalog_node.operator_version} is not runnable ({reason}){detail}"
            )
        if catalog_node.origin == "plugin" and catalog_node.plugin_release is None:
            raise GraphBuilderError(
                f"Catalog node {catalog_node.operator_id}@"
                f"{catalog_node.operator_version} has no exact Plugin release pin"
            )

        node_number = len(self._nodes) + 1
        slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            catalog_node.operator_id.lower(),
        ).strip("-")
        handle = NodeHandle(
            node_id=f"node-{node_number:04d}-{slug}",
            builder_identity=self._identity,
        )
        explicit_bindings = dict(bindings or {})
        unknown_bindings = sorted(
            set(explicit_bindings) - _artifact_type_variables(catalog_node)
        )
        if unknown_bindings:
            raise GraphBuilderError(
                f"Node {catalog_node.operator_id}@{catalog_node.operator_version} "
                "received unknown artifact type bindings: "
                + ", ".join(unknown_bindings)
            )
        self._nodes.append(
            _AuthoredNode(
                handle=handle,
                catalog_node=catalog_node,
                config=config,
                bindings=explicit_bindings,
                input_plugs=[],
                position=position,
            )
        )
        return handle

    def connect(
        self,
        source: OutputHandle,
        target: InputHandle,
        *,
        conversion_path: Sequence[SavedGraphConversion] = (),
        collection_mode: Literal["direct", "map"] = "direct",
    ) -> None:
        if (
            source.builder_identity is not self._identity
            or target.builder_identity is not self._identity
        ):
            raise GraphBuilderError("Cannot connect handles from another graph builder")

        source_node = next(
            (node for node in self._nodes if node.handle.node_id == source.node_id),
            None,
        )
        target_node = next(
            (node for node in self._nodes if node.handle.node_id == target.node_id),
            None,
        )
        if source_node is None or target_node is None:
            raise GraphBuilderError("Cannot connect a node that is not in this graph")

        source_port = next(
            (
                port
                for port in source_node.catalog_node.outputs
                if port.name == source.port
            ),
            None,
        )
        if source_port is None:
            raise GraphBuilderError(
                f"Node {source.node_id} has no output port {source.port!r}"
            )
        target_port = next(
            (
                port
                for port in target_node.catalog_node.inputs
                if port.name == target.port
            ),
            None,
        )
        if target_port is None:
            raise GraphBuilderError(
                f"Node {target.node_id} has no input port {target.port!r}"
            )
        source_shape = source_port.shape
        if collection_mode == "map":
            if source_shape.value != "many":
                raise GraphBuilderError(
                    f"Mapped connection {source.node_id}.{source.port} requires "
                    "a many-shaped output"
                )
            if target_port.instance_plugs:
                raise GraphBuilderError(
                    f"Mapped connection cannot target instance-plug input "
                    f"{target.node_id}.{target.port}"
                )
            source_shape = type(source_shape).ONE
        if source_shape not in target_port.accepted_shapes:
            raise GraphBuilderError(
                f"Cannot connect {source.node_id}.{source.port} shape "
                f"{source_shape.value!r} to {target.node_id}.{target.port}; "
                "the input does not accept that shape"
            )

        source_variable = source_port.artifact_type_variable
        resolved_source = (
            source_node.bindings.get(source_variable)
            if source_variable is not None
            else source_port.artifact_type
        )
        target_variable = target_port.artifact_type_variable
        resolved_target = (
            target_node.bindings.get(target_variable)
            if target_variable is not None
            else target_port.artifact_type
        )

        if resolved_source is None and resolved_target is None:
            raise GraphBuilderError(
                f"Cannot infer artifact type for connection {source.node_id}."
                f"{source.port} to {target.node_id}.{target.port}; bind the type "
                "variable when adding one of the nodes"
            )

        catalog_conversion_path: list[
            tuple[SavedGraphConversion, CatalogConversion]
        ] = []
        for requested in conversion_path:
            matching_conversions = [
                conversion
                for conversion in self._catalog.artifact_conversions
                if conversion.key.id == requested.id
                and conversion.key.version == requested.version
            ]
            if len(matching_conversions) != 1:
                raise GraphBuilderError(
                    f"Catalog does not declare conversion {requested.id}@"
                    f"{requested.version}"
                )
            catalog_conversion_path.append((requested, matching_conversions[0]))

        if resolved_source is None:
            if catalog_conversion_path:
                inferred_source = catalog_conversion_path[0][1].source
            else:
                if resolved_target is None:
                    raise GraphBuilderError(
                        "Source artifact type could not be resolved"
                    )
                inferred_source = resolved_target
        else:
            inferred_source = resolved_source

        current_type = inferred_source
        visited_types = {current_type}
        for requested, conversion in catalog_conversion_path:
            if conversion.source != current_type:
                raise GraphBuilderError(
                    f"Conversion {requested.id}@{requested.version} expects "
                    f"{conversion.source.id}@{conversion.source.schema_version}, "
                    f"not {current_type.id}@{current_type.schema_version}"
                )
            if conversion.target in visited_types:
                raise GraphBuilderError(
                    "Artifact conversion path must not contain a cycle"
                )
            current_type = conversion.target
            visited_types.add(current_type)

        inferred_target = current_type if resolved_target is None else resolved_target
        if current_type != inferred_target:
            raise GraphBuilderError(
                f"Cannot connect artifact type {inferred_source.id}@"
                f"{inferred_source.schema_version} to {inferred_target.id}@"
                f"{inferred_target.schema_version} with the requested conversion path"
            )

        existing_target_edges = [
            edge
            for edge in self._edges
            if edge.to_node == target.node_id and edge.to_port == target.port
        ]
        if not target_port.variadic and existing_target_edges:
            raise GraphBuilderError(
                f"Input {target.node_id}.{target.port} accepts at most one edge"
            )

        input_plug: SavedGraphInputPlug | None = None
        if target_port.instance_plugs:
            input_plug = SavedGraphInputPlug(
                id=f"plug-{len(target_node.input_plugs) + 1:04d}",
                port=target.port,
            )
        edge_number = len(self._edges) + 1
        edge = SavedGraphEdge(
            id=f"edge-{edge_number:04d}",
            from_node=source.node_id,
            from_port=source.port,
            to_node=target.node_id,
            to_port=target.port,
            to_plug=None if input_plug is None else input_plug.id,
            collection_mode=collection_mode,
            conversion_path=tuple(conversion_path),
        )
        if resolved_source is None and source_variable is not None:
            source_node.bindings[source_variable] = inferred_source
        if resolved_target is None and target_variable is not None:
            target_node.bindings[target_variable] = inferred_target
        if input_plug is not None:
            target_node.input_plugs.append(input_plug)
        self._edges.append(edge)

    def build(self) -> SavedGraphDocument:
        for authored in self._nodes:
            missing_bindings = sorted(
                _artifact_type_variables(authored.catalog_node) - set(authored.bindings)
            )
            if missing_bindings:
                raise GraphBuilderError(
                    f"Node {authored.catalog_node.operator_id}@"
                    f"{authored.catalog_node.operator_version} is missing artifact "
                    "type binding " + ", ".join(missing_bindings)
                )
            for port in authored.catalog_node.inputs:
                if not port.required:
                    continue
                has_connection = any(
                    edge.to_node == authored.handle.node_id
                    and edge.to_port == port.name
                    for edge in self._edges
                )
                if not has_connection:
                    raise GraphBuilderError(
                        f"Node {authored.catalog_node.operator_id}@"
                        f"{authored.catalog_node.operator_version} required input "
                        f"{port.name!r} has no connection"
                    )

        incoming_count = {node.handle.node_id: 0 for node in self._nodes}
        outgoing: dict[str, list[str]] = {}
        for edge in self._edges:
            incoming_count[edge.to_node] += 1
            outgoing.setdefault(edge.from_node, []).append(edge.to_node)
        queue = deque(
            node_id for node_id, count in incoming_count.items() if count == 0
        )
        visited_count = 0
        while queue:
            node_id = queue.popleft()
            visited_count += 1
            for target_node_id in outgoing.get(node_id, []):
                incoming_count[target_node_id] -= 1
                if incoming_count[target_node_id] == 0:
                    queue.append(target_node_id)
        if visited_count != len(self._nodes):
            raise GraphBuilderError("Graph contains a cycle")

        nodes = tuple(
            SavedGraphNode(
                kind=_node_kind(authored.catalog_node),
                id=authored.handle.node_id,
                operator_id=authored.catalog_node.operator_id,
                operator_version=authored.catalog_node.operator_version,
                config=authored.config,
                position=(
                    authored.position
                    if authored.position is not None
                    else GraphPoint(
                        x=float((index % 4) * 360),
                        y=float((index // 4) * 240),
                    )
                ),
                input_plugs=tuple(authored.input_plugs),
                artifact_type_bindings=tuple(
                    SavedGraphArtifactTypeBinding(
                        variable=variable,
                        artifact_type=artifact_type,
                    )
                    for variable, artifact_type in sorted(authored.bindings.items())
                ),
                plugin_release_pin=(
                    authored.catalog_node.plugin_release
                    if authored.catalog_node.origin == "plugin"
                    else None
                ),
            )
            for index, authored in enumerate(self._nodes)
        )
        return SavedGraphDocument(nodes=nodes, edges=tuple(self._edges))


__all__ = [
    "GraphBuilder",
    "GraphBuilderError",
    "InputHandle",
    "NodeHandle",
    "OutputHandle",
]
