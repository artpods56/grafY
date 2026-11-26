"""Curated discovery groups and deployment-wide catalog policy."""

from dataclasses import dataclass

from grafy_core.nodes import ServiceContractKey
from grafy_core.plugins import NodeRegistration, PluginRegistry
from grafy_shared.config.catalog import CatalogOverrides


@dataclass(frozen=True, slots=True)
class PackDefinition:
    slug: str
    title: str
    description: str
    always_on: bool = False
    default_enabled: bool = False
    operators: tuple[str, ...] = ()
    include_providers_for: tuple[ServiceContractKey, ...] = ()
    includes_project_graphs: bool = False


PACKS = (
    PackDefinition(
        "essentials",
        "Essentials",
        "Import tables, work with images, and handle sequences.",
        always_on=True,
        default_enabled=True,
        operators=(
            "table.import",
            "table.concat",
            "image.crop_regions",
            "image.draw_regions",
            "sequence.collect",
            "sequence.count",
            "sequence.item_at",
            "sequence.slice",
        ),
    ),
    PackDefinition(
        "document_ocr",
        "Document OCR",
        "Read scanned documents and extract tables from Markdown.",
        default_enabled=True,
        operators=(
            "ocr.read_document",
            "text.transliterate_cyrillic",
            "table.extract_from_markdown",
        ),
        include_providers_for=(ServiceContractKey("ocr.document", 1),),
    ),
    PackDefinition(
        "ai",
        "AI & Prompts",
        "Build prompts and schemas for chat completions.",
        operators=(
            "llm.openai_compatible.chat_completion",
            "prompt.message.create",
            "schema.builder",
            "text.input",
        ),
    ),
    PackDefinition(
        "maps",
        "Maps & GIS",
        "Import geographic data and assemble map layers.",
        operators=(
            "gis.features.to_table",
            "gis.table.to_features",
            "gis.geojson.parse",
            "gis.wfs.import",
            "gis.map.vector_layer",
            "gis.map.raster_layer",
            "gis.map.raster_mosaic",
            "gis.map.wms_layer",
            "gis.map.compose",
        ),
    ),
    PackDefinition(
        "map_toponyms",
        "Historical Map Toponyms",
        "Read, match, and georeference place names on historical maps.",
        operators=(
            "ocr.detect_tiff_text",
            "ocr.prepare_tiff_labels",
            "ocr.postprocess_tiff_regions",
            "ocr.recognize_tiff_text",
            "ocr.filter_tiff_readings",
            "ocr.places_table",
            "ocr.collect_map_places",
            "ocr.georeference_places",
            "ocr.filter_tiff_jev",
            "table.match_places",
            "table.transliterate_cyrillic",
            "text.transliterate_cyrillic",
        ),
        include_providers_for=(
            ServiceContractKey("ocr.box_detector", 1),
            ServiceContractKey("ocr.crop_reader", 1),
        ),
    ),
    PackDefinition(
        "label_studio",
        "Label Studio",
        "Exchange map text annotations with Label Studio.",
        operators=("ocr.export_label_studio", "ocr.import_label_studio"),
    ),
    PackDefinition(
        "subgraphs",
        "Sub-graphs & Constants",
        "Define graph inputs and outputs, call sibling graphs, and insert constants.",
        operators=("text.input", "value.integer"),
        includes_project_graphs=True,
    ),
)


def _contains(pack: PackDefinition, node: NodeRegistration) -> bool:
    if node.key[0] in pack.operators:
        return True
    if node.role != "provider":
        return False
    return any(
        key in pack.include_providers_for
        for output in node.node_class.output_contract.ports.values()
        for key in output.service_contracts
    )


@dataclass(frozen=True, slots=True)
class CatalogPack:
    definition: PackDefinition
    operator_count: int
    provider_count: int


class CatalogPolicy:
    """Resolve discovery metadata without changing the execution registry."""

    def __init__(
        self,
        registry: PluginRegistry,
        overrides: CatalogOverrides,
        definitions: tuple[PackDefinition, ...] = PACKS,
    ) -> None:
        operator_ids = {node.key[0] for node in registry.nodes}
        contract_keys = {contract.key for contract in registry.service_contracts}
        slugs = {pack.slug for pack in definitions}
        if len(slugs) != len(definitions):
            raise ValueError("Duplicate catalog pack slug")
        for pack in definitions:
            unknown_ids = set(pack.operators) - operator_ids
            if unknown_ids:
                raise ValueError(
                    f"Pack {pack.slug!r} has unknown operators: {sorted(unknown_ids)}"
                )
            for key in pack.include_providers_for:
                if key not in contract_keys:
                    raise ValueError(
                        f"Pack {pack.slug!r} has an unknown service contract: {key}"
                    )

        self._pack_slugs = {
            node.key: tuple(pack.slug for pack in definitions if _contains(pack, node))
            for node in registry.nodes
        }
        for node in registry.nodes:
            if node.listed and not self._pack_slugs[node.key]:
                raise ValueError(f"Listed operator {node.key} has no catalog pack")

        defaults = overrides.defaults.workspace_packs
        unknown_packs = (set(overrides.packs) | set(defaults or ())) - slugs
        if unknown_packs:
            raise ValueError(
                f"GRAFY_CATALOG_CONFIG has unknown packs: {sorted(unknown_packs)}"
            )
        unknown_operators = set(overrides.operators) - operator_ids
        if unknown_operators:
            raise ValueError(
                f"GRAFY_CATALOG_CONFIG has unknown operators: {sorted(unknown_operators)}"
            )

        self.always_on_slugs = frozenset(
            pack.slug for pack in definitions if pack.always_on
        )
        self._disabled_packs = frozenset(
            slug for slug, enabled in overrides.packs.items() if not enabled
        )
        disabled_always_on = self.always_on_slugs & self._disabled_packs
        if disabled_always_on:
            raise ValueError(
                f"GRAFY_CATALOG_CONFIG cannot disable always-on packs: {sorted(disabled_always_on)}"
            )
        self._disabled_operators = frozenset(
            operator_id
            for operator_id, enabled in overrides.operators.items()
            if not enabled
        )
        self.default_workspace_pack_slugs = tuple(
            pack.slug
            for pack in definitions
            if self.is_pack_enabled(pack.slug)
            and (
                pack.always_on
                or (pack.default_enabled if defaults is None else pack.slug in defaults)
            )
        )
        self.packs = tuple(
            self._describe(pack, registry)
            for pack in definitions
            if self.is_pack_enabled(pack.slug)
        )

    def _describe(self, pack: PackDefinition, registry: PluginRegistry) -> CatalogPack:
        members = {
            (node.key[0], node.role)
            for node in registry.nodes
            if node.listed
            and self.is_operator_enabled(node.key[0])
            and pack.slug in self.pack_slugs_for(node)
        }
        return CatalogPack(
            definition=pack,
            operator_count=sum(role == "operator" for _, role in members),
            provider_count=sum(role == "provider" for _, role in members),
        )

    def pack_slugs_for(self, registration: NodeRegistration) -> tuple[str, ...]:
        return self._pack_slugs[registration.key]

    def is_pack_enabled(self, slug: str) -> bool:
        return slug not in self._disabled_packs

    def is_operator_enabled(self, operator_id: str) -> bool:
        return operator_id not in self._disabled_operators

    def is_visible(
        self, registration: NodeRegistration, subscribed: frozenset[str]
    ) -> bool:
        return (
            registration.listed
            and self.is_operator_enabled(registration.key[0])
            and any(
                slug in subscribed and self.is_pack_enabled(slug)
                for slug in self.pack_slugs_for(registration)
            )
        )
