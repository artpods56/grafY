import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.graph_documents import (
    GraphAgent,
    GraphPoint,
    GraphArtifactTypeBinding,
    GraphConversion,
    GraphDocument,
    GraphEdge,
    GraphInputPlug,
    GraphNode,
    GraphNodeKind,
    GraphNodeLayout,
    GraphOrigin,
    GraphPresentationBinding,
    GraphPresentationAnnotation,
    GraphPresentationBindingMapping,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
    GraphProjection,
)
from grafy_core.nodes import ArtifactTypeVariable, Node
from grafy_core.schema_contracts import validate_json_schema_value

from .models import CatalogConversion, CatalogNode, CatalogPort, NodeCatalog


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


@dataclass(frozen=True, slots=True)
class CardHandle:
    """An artifact card on the canvas: a Library card or one following an output."""

    card_id: str
    artifact_ref: ArtifactRef | ArtifactRefSequence | None = None
    builder_identity: object = field(default=None, repr=False, compare=False)


type ArtifactValue = ArtifactRef | ArtifactRefSequence

InteractionEffect = Literal["filter", "highlight", "focus"]


def _value_type(value: ArtifactValue) -> ArtifactTypeKey:
    return ArtifactTypeKey(id=value.artifact_type, schema_version=value.schema_version)


def _value_owners(value: ArtifactValue) -> int:
    if isinstance(value, ArtifactRef):
        return 1
    return len(value.item_refs)


@dataclass(slots=True)
class _AuthoredNode:
    handle: NodeHandle
    catalog_node: CatalogNode
    config: dict[str, object]
    bindings: dict[str, ArtifactTypeKey]
    input_plugs: list[GraphInputPlug]
    position: GraphPoint | None
    kind: GraphNodeKind = "builtin"
    layout: GraphNodeLayout | None = None


def _fresh_id(prefix: str, start: int, taken: set[str]) -> str:
    """``prefix-NNNN`` from ``start`` up, skipping ids a loaded Graph already uses."""
    number = start
    while f"{prefix}-{number:04d}" in taken:
        number += 1
    return f"{prefix}-{number:04d}"


def _port(ports: Sequence[CatalogPort], name: str) -> CatalogPort | None:
    for port in ports:
        if port.name == name:
            return port
    return None


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
        self._edges: list[GraphEdge] = []
        self._origins: list[GraphOrigin] = []
        self._cards: list[GraphPresentationViewer] = []
        self._card_links: list[GraphPresentationLink] = []
        self._card_bindings: list[GraphPresentationBinding] = []
        # Loaded from an existing Graph and carried through unchanged: nodes the
        # catalog cannot describe (call nodes, modules, a node of an unsubscribed
        # pack), canvas annotations and Agents.
        self._opaque_nodes: dict[str, GraphNode] = {}
        self._node_order: list[str] = []
        self._annotations: list[GraphPresentationAnnotation] = []
        self._agents: list[GraphAgent] = []

    @classmethod
    def from_document(
        cls, catalog: NodeCatalog, document: GraphDocument
    ) -> "GraphBuilder":
        """A builder holding an existing Graph, to edit it with the same checks.

        Every builtin node the catalog describes becomes a handle that
        :meth:`connect`, :meth:`place` and :meth:`add_output_card` validate against;
        anything else is kept as it is. :meth:`build` returns the Graph with the
        edits applied and every untouched part, layouts and annotations included,
        exactly as loaded.
        """
        builder = cls(catalog)
        for node in document.nodes:
            builder._node_order.append(node.id)
            catalog_node = next(
                (
                    candidate
                    for candidate in catalog.nodes
                    if node.kind == "builtin"
                    and candidate.operator_id == node.operator_id
                    and candidate.operator_version == node.operator_version
                ),
                None,
            )
            if catalog_node is None:
                builder._opaque_nodes[node.id] = node
                continue
            builder._nodes.append(
                _AuthoredNode(
                    handle=NodeHandle(
                        node_id=node.id, builder_identity=builder._identity
                    ),
                    catalog_node=catalog_node,
                    config=node.config_dict(),
                    bindings=node.artifact_type_binding_map(),
                    input_plugs=list(node.input_plugs),
                    position=node.position,
                    kind=node.kind,
                    layout=node.layout,
                )
            )
        builder._edges = list(document.edges)
        builder._origins = list(document.origins)
        builder._cards = list(document.presentation.viewers)
        builder._card_links = list(document.presentation.links)
        builder._card_bindings = list(document.presentation.bindings)
        builder._annotations = list(document.presentation.annotations)
        builder._agents = list(document.agents)
        return builder

    def node(self, node_id: str) -> NodeHandle:
        """The handle of a node this builder holds, by id."""
        authored = self._find_node(node_id)
        if authored is None:
            if node_id in self._opaque_nodes:
                raise GraphBuilderError(
                    f"Node {node_id!r} is not in the catalog (a call or module "
                    "node, or a node of an unsubscribed pack); it cannot be "
                    "validated here"
                )
            raise GraphBuilderError(f"No node {node_id!r} in this graph")
        return authored.handle

    def card(self, card_id: str) -> CardHandle:
        """The handle of a card this builder holds, by id."""
        for viewer in self._cards:
            if viewer.id == card_id:
                return CardHandle(
                    card_id=viewer.id,
                    artifact_ref=viewer.artifact_ref,
                    builder_identity=self._identity,
                )
        raise GraphBuilderError(f"No card {card_id!r} in this graph")

    def _node_ids(self) -> set[str]:
        return {node.handle.node_id for node in self._nodes} | set(self._opaque_nodes)

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
        node_id: str | None = None,
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
            node_id=node_id,
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
        node_id: str | None = None,
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
            node_id=node_id,
        )

    def _append_node(
        self,
        catalog_node: CatalogNode,
        config: dict[str, object],
        *,
        bindings: Mapping[str, ArtifactTypeKey] | None,
        position: GraphPoint | None,
        node_id: str | None = None,
    ) -> NodeHandle:
        if not catalog_node.runnable:
            raise GraphBuilderError(
                f"Catalog node {catalog_node.operator_id}@"
                f"{catalog_node.operator_version} is in a catalog this build cannot run"
            )

        if node_id is None:
            node_number = len(self._nodes) + 1
            slug = re.sub(
                r"[^a-z0-9]+",
                "-",
                catalog_node.operator_id.lower(),
            ).strip("-")
            node_id = f"node-{node_number:04d}-{slug}"
            while node_id in self._node_ids():
                node_number += 1
                node_id = f"node-{node_number:04d}-{slug}"
        elif node_id.strip() != node_id or node_id == "":
            raise GraphBuilderError(
                f"Node id {node_id!r} must be non-blank and trimmed"
            )
        if node_id in self._node_ids():
            raise GraphBuilderError(f"Node id {node_id!r} is already in this graph")
        handle = NodeHandle(node_id=node_id, builder_identity=self._identity)
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
        self._node_order.append(node_id)
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
        conversion_path: Sequence[GraphConversion] = (),
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

        catalog_conversion_path: list[tuple[GraphConversion, CatalogConversion]] = []
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

        if not target_port.variadic and self._input_is_satisfied(target):
            raise GraphBuilderError(
                f"Input {target.node_id}.{target.port} accepts at most one edge"
            )

        input_plug: GraphInputPlug | None = None
        if target_port.instance_plugs:
            input_plug = GraphInputPlug(
                id=_fresh_id(
                    "plug",
                    len(target_node.input_plugs) + 1,
                    {plug.id for plug in target_node.input_plugs},
                ),
                port=target.port,
            )
        edge = GraphEdge(
            id=_fresh_id(
                "edge", len(self._edges) + 1, {edge.id for edge in self._edges}
            ),
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

    def _find_node(self, node_id: str) -> _AuthoredNode | None:
        for authored in self._nodes:
            if authored.handle.node_id == node_id:
                return authored
        return None

    def _input_is_satisfied(self, target: InputHandle) -> bool:
        for edge in self._edges:
            if edge.to_node == target.node_id and edge.to_port == target.port:
                return True
        for origin in self._origins:
            if origin.to_node == target.node_id and origin.to_port == target.port:
                return True
        return False

    def _own_card(self, card: CardHandle) -> GraphPresentationViewer:
        if card.builder_identity is not self._identity:
            raise GraphBuilderError("Cannot use a card from another graph builder")
        for viewer in self._cards:
            if viewer.id == card.card_id:
                return viewer
        raise GraphBuilderError(f"Card {card.card_id} is not in this graph")

    def _next_card_id(self) -> str:
        return _fresh_id(
            "artifact-viewer", len(self._cards) + 1, {card.id for card in self._cards}
        )

    def _card_position(self, position: GraphPoint | None) -> GraphPoint:
        if position is not None:
            return position
        index = len(self._cards)
        return GraphPoint(
            x=float(4 * 360 + (index % 2) * 380), y=float((index // 2) * 320)
        )

    def place(
        self,
        target: InputHandle,
        source: ArtifactRef | ArtifactRefSequence | CardHandle,
        *,
        conversion_path: Sequence[GraphConversion] = (),
        collection_mode: Literal["direct", "map"] = "direct",
    ) -> None:
        """Satisfy ``target`` with a stored artifact instead of an upstream edge.

        This writes an origin: the exact reference becomes the input, and no node is
        added. Passing a Library card (from :meth:`add_artifact_card`) records the
        card as the owner of that contribution, the way dropping a card on an input
        does in the Workbench.
        """
        if target.builder_identity is not self._identity:
            raise GraphBuilderError("Cannot place into a handle from another builder")
        card_id: str | None = None
        if isinstance(source, CardHandle):
            viewer = self._own_card(source)
            if viewer.artifact_ref is None:
                raise GraphBuilderError(
                    f"Card {viewer.id} follows a node output and holds no artifact"
                )
            value: ArtifactValue = viewer.artifact_ref
            card_id = viewer.id
        else:
            value = source
        target_node = self._find_node(target.node_id)
        if target_node is None:
            raise GraphBuilderError(
                "Cannot place into a node that is not in this graph"
            )
        target_port = _port(target_node.catalog_node.inputs, target.port)
        if target_port is None:
            raise GraphBuilderError(
                f"Node {target.node_id} has no input port {target.port!r}"
            )
        shape = type(target_port.shape)
        value_shape = shape.ONE if isinstance(value, ArtifactRef) else shape.MANY
        if collection_mode == "map":
            if value_shape is not shape.MANY:
                raise GraphBuilderError("A mapped origin needs an artifact sequence")
            value_shape = shape.ONE
        if value_shape not in target_port.accepted_shapes:
            raise GraphBuilderError(
                f"Input {target.node_id}.{target.port} does not accept a "
                f"{value_shape.value!r} artifact value"
            )
        if not target_port.variadic and self._input_is_satisfied(target):
            raise GraphBuilderError(
                f"Input {target.node_id}.{target.port} is already satisfied"
            )
        delivered = self._convert(_value_type(value), conversion_path)
        variable = target_port.artifact_type_variable
        if variable is not None:
            bound = target_node.bindings.get(variable)
            if bound is not None and bound != delivered:
                raise GraphBuilderError(
                    f"Input {target.node_id}.{target.port} is bound to "
                    f"{bound.id}@{bound.schema_version}, not "
                    f"{delivered.id}@{delivered.schema_version}"
                )
        elif delivered not in {target_port.artifact_type, *target_port.also_accepts}:
            raise GraphBuilderError(
                f"Input {target.node_id}.{target.port} does not accept "
                f"{delivered.id}@{delivered.schema_version}"
            )

        input_plug: GraphInputPlug | None = None
        if target_port.instance_plugs:
            input_plug = GraphInputPlug(
                id=_fresh_id(
                    "plug",
                    len(target_node.input_plugs) + 1,
                    {plug.id for plug in target_node.input_plugs},
                ),
                port=target.port,
            )
        origin = GraphOrigin(
            id=_fresh_id(
                "origin",
                len(self._origins) + 1,
                {origin.id for origin in self._origins},
            ),
            to_node=target.node_id,
            to_port=target.port,
            to_plug=None if input_plug is None else input_plug.id,
            value=value,
            source_card_ids=(
                None if card_id is None else (card_id,) * _value_owners(value)
            ),
            collection_mode=collection_mode,
            conversion_path=tuple(conversion_path),
        )
        if variable is not None:
            target_node.bindings[variable] = delivered
        if input_plug is not None:
            target_node.input_plugs.append(input_plug)
        self._origins.append(origin)

    def _convert(
        self,
        start: ArtifactTypeKey,
        conversion_path: Sequence[GraphConversion],
    ) -> ArtifactTypeKey:
        current = start
        visited = {current}
        for requested in conversion_path:
            matching = [
                conversion
                for conversion in self._catalog.artifact_conversions
                if conversion.key.id == requested.id
                and conversion.key.version == requested.version
            ]
            if len(matching) != 1:
                raise GraphBuilderError(
                    f"Catalog does not declare conversion {requested.id}@"
                    f"{requested.version}"
                )
            conversion = matching[0]
            if conversion.source != current:
                raise GraphBuilderError(
                    f"Conversion {requested.id}@{requested.version} expects "
                    f"{conversion.source.id}@{conversion.source.schema_version}, "
                    f"not {current.id}@{current.schema_version}"
                )
            if conversion.target in visited:
                raise GraphBuilderError(
                    "Artifact conversion path must not contain a cycle"
                )
            current = conversion.target
            visited.add(current)
        return current

    def add_artifact_card(
        self,
        artifact: ArtifactRef | ArtifactRefSequence,
        *,
        position: GraphPoint | None = None,
        card_id: str | None = None,
    ) -> CardHandle:
        """Show a stored artifact (or an ordered sequence of them) on the canvas.

        The Workbench's Library drop: the card carries the reference and executes
        nothing. Pass the card to :meth:`place` to feed it into a node input.
        """
        viewer = GraphPresentationViewer(
            id=card_id or self._next_card_id(),
            position=self._card_position(position),
            artifact_ref=artifact,
        )
        self._add_card(viewer)
        return CardHandle(
            card_id=viewer.id,
            artifact_ref=artifact,
            builder_identity=self._identity,
        )

    def add_output_card(
        self,
        source: OutputHandle,
        *,
        position: GraphPoint | None = None,
        projection: Sequence[str] = (),
        card_id: str | None = None,
    ) -> CardHandle:
        """Show what a node output produces, the Workbench's output-port drop.

        The card follows the output across Runs; ``projection`` previews one nested
        field of the produced artifact instead of the whole value.
        """
        if source.builder_identity is not self._identity:
            raise GraphBuilderError("Cannot link a handle from another graph builder")
        source_node = self._find_node(source.node_id)
        if source_node is None:
            raise GraphBuilderError("Cannot link a node that is not in this graph")
        if _port(source_node.catalog_node.outputs, source.port) is None:
            raise GraphBuilderError(
                f"Node {source.node_id} has no output port {source.port!r}"
            )
        viewer = GraphPresentationViewer(
            id=card_id or self._next_card_id(),
            position=self._card_position(position),
            mode="artifact",
        )
        self._add_card(viewer)
        self._card_links.append(
            GraphPresentationLink(
                id=_fresh_id(
                    "artifact-viewer-edge",
                    len(self._card_links) + 1,
                    {link.id for link in self._card_links},
                ),
                source_node_id=source.node_id,
                source_port_name=source.port,
                target_viewer_id=viewer.id,
                projection=(
                    GraphProjection(path=tuple(projection)) if projection else None
                ),
            )
        )
        return CardHandle(card_id=viewer.id, builder_identity=self._identity)

    def _add_card(self, viewer: GraphPresentationViewer) -> None:
        for existing in self._cards:
            if existing.id == viewer.id:
                raise GraphBuilderError(f"Card id {viewer.id!r} is already in use")
        self._cards.append(viewer)

    def bind_cards(
        self,
        source: CardHandle,
        target: CardHandle,
        fields: Mapping[str, str],
        *,
        effects: Sequence[InteractionEffect] = ("highlight", "focus"),
    ) -> str:
        """Link a selection on ``source`` to ``target`` by matching key fields.

        ``fields`` maps a field of the source card's selected rows or features to
        the field of the target card it must equal. ``effects`` decide what the
        target does with the matches; the default is the Workbench's own.
        """
        source_viewer = self._own_card(source)
        target_viewer = self._own_card(target)
        if not fields:
            raise GraphBuilderError("A card binding needs at least one field pair")
        try:
            binding = GraphPresentationBinding(
                id=_fresh_id(
                    "artifact-viewer-binding",
                    len(self._card_bindings) + 1,
                    {binding.id for binding in self._card_bindings},
                ),
                source_viewer_id=source_viewer.id,
                target_viewer_id=target_viewer.id,
                mappings=tuple(
                    GraphPresentationBindingMapping(
                        source_field=source_field, target_field=target_field
                    )
                    for source_field, target_field in fields.items()
                ),
                effects=tuple(effects),
            )
        except ValidationError as exc:
            raise GraphBuilderError(f"Invalid card binding: {exc}") from exc
        self._card_bindings.append(binding)
        return binding.id

    def build(self, *, require_complete: bool = True) -> GraphDocument:
        """The Graph document, checked for cycles and, by default, completeness.

        ``require_complete=False`` skips the missing-binding and required-input
        checks, for a Graph that is being edited and is not runnable yet, the state
        a canvas is in between two user gestures.
        """
        if require_complete:
            self._require_complete()

        node_ids = self._node_ids()
        incoming_count = {node_id: 0 for node_id in node_ids}
        outgoing: dict[str, list[str]] = {}
        for edge in self._edges:
            if edge.to_node not in incoming_count or edge.from_node not in node_ids:
                raise GraphBuilderError(
                    f"Edge {edge.id} connects a node that is not in this graph"
                )
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
        if visited_count != len(node_ids):
            raise GraphBuilderError("Graph contains a cycle")

        authored_nodes = {node.handle.node_id: node for node in self._nodes}
        nodes: list[GraphNode] = []
        for index, node_id in enumerate(self._node_order):
            opaque = self._opaque_nodes.get(node_id)
            if opaque is not None:
                nodes.append(opaque)
                continue
            authored = authored_nodes[node_id]
            nodes.append(
                GraphNode(
                    kind=authored.kind,
                    id=node_id,
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
                    layout=authored.layout,
                    input_plugs=tuple(authored.input_plugs),
                    artifact_type_bindings=tuple(
                        GraphArtifactTypeBinding(
                            variable=variable,
                            artifact_type=artifact_type,
                        )
                        for variable, artifact_type in sorted(authored.bindings.items())
                    ),
                )
            )
        try:
            return GraphDocument(
                agents=tuple(self._agents),
                nodes=tuple(nodes),
                edges=tuple(self._edges),
                origins=tuple(self._origins),
                presentation=GraphPresentationDocument(
                    viewers=tuple(self._cards),
                    links=tuple(self._card_links),
                    bindings=tuple(self._card_bindings),
                    annotations=tuple(self._annotations),
                ),
            )
        except ValidationError as exc:
            raise GraphBuilderError(f"Graph document is invalid: {exc}") from exc

    def _require_complete(self) -> None:
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
                handle = authored.handle.input(port.name)
                if not self._input_is_satisfied(handle):
                    raise GraphBuilderError(
                        f"Node {authored.catalog_node.operator_id}@"
                        f"{authored.catalog_node.operator_version} required input "
                        f"{port.name!r} has no connection"
                    )


__all__ = [
    "CardHandle",
    "GraphBuilder",
    "GraphBuilderError",
    "InputHandle",
    "NodeHandle",
    "OutputHandle",
]
