import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import type { GraphPresentation } from "@/features/workbench/canvas/artifact-viewer";
import { defaultNodeConfig } from "@/features/workbench/canvas/types";
import type { CellCardSurfaceData } from "@/features/workbench/cell-canvas/cell-contracts";
import {
  cellGraphFromAuthoredDocument,
  type CellNodeRunState,
} from "@/features/workbench/cell-canvas/cell-document-adapter";
import { createStressCellGraph } from "@/features/workbench/cell-canvas/cell-graphs";
import {
  CELL_SIZE,
  collectionHeightCells,
  collectionRowOffset,
  type CellCardModel,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
} from "@/features/workbench/cell-canvas/cell-model";
import {
  COLLECTION_OPERATOR_ID,
  COLLECTION_PORT,
} from "@/features/workbench/model/collection-spec";
import type { AuthoredGraphDocument } from "@/features/workbench/model/graph-document";

import {
  ASK_A_MODEL_OPERATOR_ID,
  askAModelRegistry,
} from "../../fixtures/ask-a-model-registry";

const IMAGE = "image.raster";
const MARKDOWN = "text.markdown";
const TABLE = "table.data";

function input(
  id: string,
  rowOffset: number,
  artifactTypeId: string,
  shape: CellPort["shape"],
  required = false,
): CellPort {
  return {
    id,
    name: id,
    direction: "input",
    rowOffset,
    artifactTypeId,
    shape,
    required,
  };
}

function output(
  id: string,
  rowOffset: number,
  artifactTypeId: string,
  shape: CellPort["shape"],
): CellPort {
  return {
    id,
    name: id,
    direction: "output",
    rowOffset,
    artifactTypeId,
    shape,
  };
}

function pipe(
  id: string,
  [sourceCardId, sourcePortId]: [string, string],
  [targetCardId, targetPortId]: [string, string],
): CellPipeModel {
  return {
    id,
    sourceCardId,
    sourcePortId,
    targetCardId,
    targetPortId,
    enabled: true,
  };
}

export interface RealAnatomyShowcaseGraph {
  graph: CellGraph;
  surfaceById: Record<string, CellCardSurfaceData>;
}

/**
 * A real node, not a hand-drawn one: the LLM plugin's "Ask a model" spec from
 * the registry fixture, placed the way the workbench drops it (the spec's
 * default config), and turned into a card by the same adapter the workbench
 * seam uses.
 */
export function createAskAModelCard(cell: { col: number; row: number }) {
  const spec = askAModelRegistry.nodes.find(
    (node) => node.operator_id === ASK_A_MODEL_OPERATOR_ID,
  );
  if (!spec) throw new Error("The registry fixture lost its Ask a model spec");
  const { graph, surfaceById } = cellGraphFromAuthoredDocument(
    {
      name: "Ask a model",
      nodes: [
        {
          id: "ask-model",
          kind: "builtin",
          operator_id: spec.operator_id,
          operator_version: spec.operator_version,
          position: { x: cell.col * CELL_SIZE, y: cell.row * CELL_SIZE },
          config: defaultNodeConfig(spec),
          input_plugs: [],
          artifact_type_bindings: [],
        },
      ],
      edges: [],
      origins: [],
      agents: [],
    },
    askAModelRegistry,
  );
  const card = graph.cards[0];
  const surface = card ? surfaceById[card.id] : undefined;
  if (!card || !surface)
    throw new Error("The adapter dropped the Ask a model node");
  return { card, surface };
}

export function createRealAnatomyShowcaseGraph(): RealAnatomyShowcaseGraph {
  const askModel = createAskAModelCard({ col: 32, row: 24 });
  const cards: CellCardModel[] = [
    {
      id: "frame-ingest",
      title: "Document Ingestion & OCR",
      subtitle: "OCR stage",
      kind: "annotation",
      status: "idle",
      col: 2,
      row: 0,
      widthCells: 25,
      heightCells: 26,
      ports: [],
      resizable: true,
      resizeBounds: { minWidthCells: 16, minHeightCells: 12 },
    },
    {
      id: "doc-scan",
      title: "Invoice Scan",
      subtitle: "PNG · 1600 × 1200",
      kind: "artifact",
      status: "done",
      col: 2,
      row: 2,
      widthCells: 8,
      heightCells: 6,
      // Level with Extract Invoice's source port, so the pipe runs straight.
      ports: [output("image", 4, IMAGE, "one")],
    },
    {
      id: "ocr-extract",
      title: "Extract Invoice",
      subtitle: "Image → Text",
      kind: "operator",
      status: "done",
      col: 13,
      row: 4,
      widthCells: 12,
      heightCells: 18,
      resizable: true,
      resizeBounds: {
        minWidthCells: 12,
        maxWidthCells: 20,
        minHeightCells: 18,
        maxHeightCells: 28,
      },
      ports: [
        input("source", 2, IMAGE, "one", true),
        input("extra_hints::plug-1", 6, MARKDOWN, "one"),
        input("extra_hints::plug-2", 8, MARKDOWN, "one"),
        output("text", 2, MARKDOWN, "one"),
        output("pages", 4, TABLE, "many"),
      ],
    },
    {
      id: "page-batch",
      title: "Page Tables",
      subtitle: "Collection · 2 items",
      kind: "collection",
      status: "done",
      col: 32,
      row: 4,
      widthCells: 10,
      heightCells: collectionHeightCells(3),
      ports: [
        input("items::plug-1", collectionRowOffset(0), TABLE, "many"),
        input("items::plug-2", collectionRowOffset(1), TABLE, "many"),
        output("items", collectionRowOffset(0), TABLE, "many"),
      ],
    },
    {
      id: "summarize",
      title: "Reconcile Totals",
      subtitle: "Table → Summary",
      kind: "operator",
      status: "done",
      col: 50,
      row: 4,
      widthCells: 12,
      heightCells: 8,
      ports: [
        input("tables", 2, TABLE, "many", true),
        input("context", 4, MARKDOWN, "one"),
        output("summary", 2, MARKDOWN, "one"),
      ],
    },
    {
      id: "reviewer-agent",
      title: "Audit Reviewer",
      subtitle: "Agent · Claude Opus 5.5",
      kind: "agent",
      status: "idle",
      col: 50,
      row: 18,
      widthCells: 14,
      heightCells: 8,
      resizable: true,
      resizeBounds: {
        minWidthCells: 12,
        maxWidthCells: 20,
        minHeightCells: 8,
        maxHeightCells: 16,
      },
      ports: [
        input("artifact", 2, MARKDOWN, "one", true),
        output("verdict", 2, MARKDOWN, "one"),
      ],
    },
    {
      id: "note-hint",
      title: "Seam & Projection Note",
      subtitle: "Canvas annotation",
      kind: "annotation",
      status: "idle",
      col: 32,
      row: 16,
      widthCells: 12,
      heightCells: 6,
      ports: [],
    },
    askModel.card,
  ];

  const pipes = [
    pipe("scan-to-ocr", ["doc-scan", "image"], ["ocr-extract", "source"]),
    pipe(
      "ocr-to-collection",
      ["ocr-extract", "pages"],
      ["page-batch", "items::plug-1"],
    ),
    {
      ...pipe(
        "collection-to-summarize",
        ["page-batch", "items"],
        ["summarize", "tables"],
      ),
      projectionLabel: "tables.line_items",
      conversionLabel: "List → Table",
    },
    pipe(
      "ocr-text-to-summarize",
      ["ocr-extract", "text"],
      ["summarize", "context"],
    ),
    pipe(
      "summarize-to-agent",
      ["summarize", "summary"],
      ["reviewer-agent", "artifact"],
    ),
  ];

  return {
    graph: { cards, pipes },
    surfaceById: {
      "frame-ingest": {
        kind: "annotation",
        variant: "frame",
        layer: "under-cards",
        color: "blue",
        bodyText: "Scan-to-OCR pipeline with dynamic hint plugs.",
      },
      "doc-scan": {
        kind: "artifact",
        previewKind: "image",
        artifactTypeId: IMAGE,
        typeLabel: "Raster image",
        filename: "invoice_scan.png",
        dimensionsLabel: "1600 × 1200",
        byteSizeLabel: "1.8 MB",
      },
      "ocr-extract": {
        kind: "operator",
        statusLabel: "240 ms",
        instancePlugGroups: [
          {
            portName: "extra_hints",
            title: "Extra hints",
            artifactTypeId: MARKDOWN,
            shape: "one",
            startRowOffset: 6,
            canAdd: true,
            plugs: [
              {
                plugId: "extra_hints::plug-1",
                label: "Hint 1",
                connected: false,
                connectionMeta: "Vendor header layout",
              },
              {
                plugId: "extra_hints::plug-2",
                label: "Hint 2",
                connected: false,
                connectionMeta: "Currency locale",
              },
            ],
          },
        ],
        configFields: [
          {
            id: "engine",
            label: "Engine",
            kind: "select",
            value: "mistral-ocr",
            span: 1,
            options: [{ value: "mistral-ocr", label: "Mistral OCR" }],
          },
          {
            id: "deskew",
            label: "Deskew",
            kind: "toggle",
            value: true,
            span: 1,
          },
          {
            id: "prompt",
            label: "Prompt",
            kind: "text",
            value: "Extract line items and tax totals",
            span: 2,
            denseRows: 1,
          },
        ],
        appendix: {
          title: "Extracted markdown",
          kindBadge: "Text value",
          heightCells: 4,
          collapsed: false,
          summaryText: "240 tokens · 2 tables",
          itemCount: 2,
          previewLines: ["# INVOICE #4092", "| Item | Qty | Net |"],
        },
      },
      "page-batch": {
        kind: "collection",
        artifactTypeId: TABLE,
        typeLabel: "List of Data table",
        showSparePlug: true,
        members: [
          {
            id: "items::plug-1",
            label: "OCR pages",
            artifactTypeId: TABLE,
            typeLabel: "Data table",
            meta: "12 rows",
          },
          {
            id: "items::plug-2",
            label: "Archive ledger",
            artifactTypeId: TABLE,
            typeLabel: "Data table",
            meta: "4 rows",
          },
        ],
      },
      summarize: {
        kind: "operator",
        statusLabel: "110 ms",
        configFields: [
          {
            id: "currency",
            label: "Currency",
            kind: "select",
            value: "EUR",
            span: 1,
            options: [
              { value: "EUR", label: "EUR" },
              { value: "USD", label: "USD" },
            ],
          },
          {
            id: "strict",
            label: "Strict balance",
            kind: "toggle",
            value: true,
            span: 1,
          },
        ],
      },
      "reviewer-agent": {
        kind: "agent",
        modelLabel: "Claude Opus 5.5",
        agentStatus: "idle",
        linkedToolCount: 3,
        recentToolRows: [
          {
            id: "tool-1",
            toolName: "verify_vat_rate",
            status: "done",
            summary: "19% VAT verified",
          },
          {
            id: "tool-2",
            toolName: "flag_anomaly",
            status: "done",
            summary: "0 discrepancies",
          },
        ],
        lastMessageSnippet:
          "All invoice line items reconcile with ledger totals.",
      },
      "note-hint": {
        kind: "annotation",
        variant: "note",
        color: "amber",
        layer: "under-cards",
        bodyText:
          "The scan's port lines up with the OCR input, so its pipe runs straight between the wells; collection-to-summarize renders a 6×1 projection pill.",
      },
      [askModel.card.id]: askModel.surface,
    },
  };
}

export interface StressGroupBenchmarkGraph {
  graph: CellGraph;
  groupCardIds: readonly string[];
  anchorCardId: string;
}

export function createStressGroupBenchmarkGraph(): StressGroupBenchmarkGraph {
  return {
    graph: createStressCellGraph(),
    groupCardIds: [
      "stress-1-3",
      "stress-1-4",
      "stress-1-5",
      "stress-2-3",
      "stress-2-4",
      "stress-2-5",
    ],
    anchorCardId: "stress-2-4",
  };
}

// ---------------------------------------------------------------------------
// Real AuthoredGraphDocument-backed Showcase + live registry merge

function specPort(
  name: string,
  title: string,
  direction: Port["direction"],
  artifactTypeId: string | null,
  options: Partial<Port> = {},
): Port {
  return {
    name,
    kind: "artifact",
    title,
    description: null,
    direction,
    artifact_type: artifactTypeId
      ? { id: artifactTypeId, schema_version: 1 }
      : null,
    artifact_type_variable: artifactTypeId ? null : "T",
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: direction === "input",
    ...options,
  };
}

const SHOWCASE_BUILTIN_SPECS: readonly NodeSpec[] = [
  {
    operator_id: "showcase.ocr_extract",
    operator_version: 1,
    plugin_slug: "showcase",
    origin: "builtin",
    title: "Extract Invoice",
    description:
      "Extracts structured tables and markdown from a scanned image.",
    catalog_visible: true,
    runnable: true,
    input_schema: {},
    output_schema: {},
    inputs: [
      specPort("source", "source", "input", IMAGE),
      specPort("extra_hints", "Extra hints", "input", MARKDOWN, {
        instance_plugs: true,
        required: false,
      }),
    ],
    outputs: [
      specPort("text", "text", "output", MARKDOWN),
      specPort("pages", "pages", "output", TABLE, {
        shape: "many",
        accepted_shapes: ["many"],
      }),
    ],
    config_schema: {
      type: "object",
      properties: {
        engine: {
          type: "string",
          title: "Engine",
          enum: ["mistral-ocr", "reducto"],
          default: "mistral-ocr",
        },
        deskew: { type: "boolean", title: "Deskew", default: true },
        prompt: {
          type: "string",
          title: "Prompt",
          default: "Extract line items and tax totals",
        },
      },
    },
  },
  {
    operator_id: COLLECTION_OPERATOR_ID,
    operator_version: 1,
    plugin_slug: "builtin",
    origin: "builtin",
    title: "Page Tables",
    description: "Collects artifacts into an ordered sequence.",
    catalog_visible: true,
    runnable: true,
    input_schema: {},
    output_schema: {},
    inputs: [
      specPort(COLLECTION_PORT, "Items", "input", null, {
        instance_plugs: true,
        required: false,
      }),
    ],
    outputs: [
      specPort("items", "items", "output", null, {
        shape: "many",
        accepted_shapes: ["many"],
      }),
    ],
    config_schema: { type: "object", properties: {} },
  },
  {
    operator_id: "showcase.reconcile_totals",
    operator_version: 1,
    plugin_slug: "showcase",
    origin: "builtin",
    title: "Reconcile Totals",
    description: "Reconciles extracted tables against contextual notes.",
    catalog_visible: true,
    runnable: true,
    input_schema: {},
    output_schema: {},
    inputs: [
      specPort("tables", "tables", "input", TABLE, {
        shape: "many",
        accepted_shapes: ["many"],
      }),
      specPort("context", "context", "input", MARKDOWN, { required: false }),
    ],
    outputs: [specPort("summary", "summary", "output", MARKDOWN)],
    config_schema: {
      type: "object",
      properties: {
        currency: {
          type: "string",
          title: "Currency",
          enum: ["EUR", "USD"],
          default: "EUR",
        },
        strict: { type: "boolean", title: "Strict balance", default: true },
      },
    },
  },
];

export const showcaseFallbackRegistry: NodeRegistry = {
  ...askAModelRegistry,
  plugins: [
    ...askAModelRegistry.plugins,
    {
      slug: "showcase",
      title: "Showcase",
      origin: "builtin",
      entry_kind: "plugin",
    },
  ],
  artifact_types: [
    ...askAModelRegistry.artifact_types,
    {
      key: { id: IMAGE, schema_version: 1 },
      title: "Raster image",
      bundle: { format: "inline-json", version: 1 },
      payload_schema: {},
      field_projections: [],
    },
    {
      key: { id: MARKDOWN, schema_version: 1 },
      title: "Markdown",
      bundle: { format: "inline-json", version: 1 },
      payload_schema: {},
      field_projections: [],
    },
    {
      key: { id: TABLE, schema_version: 1 },
      title: "Data table",
      bundle: { format: "inline-json", version: 1 },
      payload_schema: {},
      field_projections: [],
    },
  ],
  nodes: [...askAModelRegistry.nodes, ...SHOWCASE_BUILTIN_SPECS],
};

function specKey(spec: Pick<NodeSpec, "operator_id" | "operator_version">) {
  return `${spec.operator_id}@${spec.operator_version}`;
}

/**
 * Merges a live workspace `NodeRegistry` with the showcase fallback specs,
 * preferring live backend definitions whenever both provide an operator.
 */
export function mergeShowcaseRegistry(
  liveRegistry?: NodeRegistry | null,
): NodeRegistry {
  if (!liveRegistry) return showcaseFallbackRegistry;
  const seenNodes = new Set(liveRegistry.nodes.map(specKey));
  const seenTypes = new Set(
    liveRegistry.artifact_types.map(
      (item) => `${item.key.id}@${item.key.schema_version}`,
    ),
  );
  const seenPlugins = new Set(liveRegistry.plugins.map((p) => p.slug));
  return {
    plugins: [
      ...liveRegistry.plugins,
      ...showcaseFallbackRegistry.plugins.filter(
        (p) => !seenPlugins.has(p.slug),
      ),
    ],
    artifact_types: [
      ...liveRegistry.artifact_types,
      ...showcaseFallbackRegistry.artifact_types.filter(
        (item) => !seenTypes.has(`${item.key.id}@${item.key.schema_version}`),
      ),
    ],
    artifact_conversions: liveRegistry.artifact_conversions,
    nodes: [
      ...liveRegistry.nodes,
      ...showcaseFallbackRegistry.nodes.filter(
        (spec) => !seenNodes.has(specKey(spec)),
      ),
    ],
  };
}

export interface ShowcaseAuthoredState {
  document: AuthoredGraphDocument;
  presentation: GraphPresentation;
  nodeRunState: Readonly<Record<string, CellNodeRunState>>;
}

export function createShowcaseAuthoredDocument(
  registry: NodeRegistry,
): ShowcaseAuthoredState {
  const askSpec =
    registry.nodes.find((n) => n.operator_id === ASK_A_MODEL_OPERATOR_ID) ??
    showcaseFallbackRegistry.nodes.find(
      (n) => n.operator_id === ASK_A_MODEL_OPERATOR_ID,
    );
  const askVersion = askSpec?.operator_version ?? 1;
  const askConfig = askSpec ? defaultNodeConfig(askSpec) : {};

  const document: AuthoredGraphDocument = {
    name: "Invoice Extraction Showcase",
    nodes: [
      {
        id: "ocr-extract",
        kind: "builtin",
        operator_id: "showcase.ocr_extract",
        operator_version: 1,
        position: { x: 13 * CELL_SIZE, y: 4 * CELL_SIZE },
        layout: {
          width: 12 * CELL_SIZE,
          body_height: 14 * CELL_SIZE,
          appendix_height: 4 * CELL_SIZE,
        },
        config: {
          engine: "mistral-ocr",
          deskew: true,
          prompt: "Extract line items and tax totals",
        },
        input_plugs: [
          { port: "extra_hints", id: "plug-1" },
          { port: "extra_hints", id: "plug-2" },
        ],
        artifact_type_bindings: [],
      },
      {
        id: "page-batch",
        kind: "builtin",
        operator_id: COLLECTION_OPERATOR_ID,
        operator_version: 1,
        position: { x: 32 * CELL_SIZE, y: 4 * CELL_SIZE },
        layout: {
          width: 10 * CELL_SIZE,
          body_height: null,
          appendix_height: null,
        },
        config: {},
        input_plugs: [
          { port: COLLECTION_PORT, id: "plug-1" },
          { port: COLLECTION_PORT, id: "plug-2" },
        ],
        artifact_type_bindings: [
          { variable: "T", artifact_type: { id: TABLE, schema_version: 1 } },
        ],
      },
      {
        id: "summarize",
        kind: "builtin",
        operator_id: "showcase.reconcile_totals",
        operator_version: 1,
        position: { x: 50 * CELL_SIZE, y: 4 * CELL_SIZE },
        layout: {
          width: 12 * CELL_SIZE,
          body_height: null,
          appendix_height: null,
        },
        config: { currency: "EUR", strict: true },
        input_plugs: [],
        artifact_type_bindings: [],
      },
      {
        id: "ask-model",
        kind: "builtin",
        operator_id: ASK_A_MODEL_OPERATOR_ID,
        operator_version: askVersion,
        position: { x: 32 * CELL_SIZE, y: 24 * CELL_SIZE },
        layout: null,
        config: askConfig,
        input_plugs: [],
        artifact_type_bindings: [],
      },
    ],
    edges: [
      {
        id: "ocr-to-collection",
        from_node: "ocr-extract",
        from_port: "pages",
        to_node: "page-batch",
        to_port: COLLECTION_PORT,
        to_plug: "plug-1",
        enabled: true,
        collection_mode: "direct",
        projection: null,
        conversion_path: [],
        route_offset: null,
      },
      {
        id: "collection-to-summarize",
        from_node: "page-batch",
        from_port: "items",
        to_node: "summarize",
        to_port: "tables",
        to_plug: null,
        enabled: true,
        collection_mode: "direct",
        projection: { path: ["tables", "line_items"] },
        conversion_path: [{ id: "table.to_list", version: 1 }],
        route_offset: null,
      },
      {
        id: "ocr-text-to-summarize",
        from_node: "ocr-extract",
        from_port: "text",
        to_node: "summarize",
        to_port: "context",
        to_plug: null,
        enabled: true,
        collection_mode: "direct",
        projection: null,
        conversion_path: [],
        route_offset: null,
      },
    ],
    origins: [
      {
        id: "scan-origin",
        to_node: "ocr-extract",
        to_port: "source",
        to_plug: null,
        value: {
          artifact_id: "invoice-scan-1",
          artifact_type: IMAGE,
          schema_version: 1,
        },
        source_card_ids: ["doc-scan"],
        collection_mode: "direct",
        conversion_path: [],
      },
    ],
    agents: [
      {
        id: "reviewer-agent",
        name: "Audit Reviewer",
        instructions: "All invoice line items reconcile with ledger totals.",
        model: {
          kind: "custom",
          model: "Claude Opus 5.5",
          endpoint: "https://api.anthropic.com",
        },
        width: 14 * CELL_SIZE,
        height: 8 * CELL_SIZE,
        position: { x: 50 * CELL_SIZE, y: 18 * CELL_SIZE },
        context: [],
        tools: [
          {
            id: "t1",
            name: "verify_vat_rate",
            node_id: "summarize",
            description: "19% VAT verified",
            filled_ports: [],
            returned_ports: ["summary"],
          },
          {
            id: "t2",
            name: "flag_anomaly",
            node_id: "ocr-extract",
            description: "0 discrepancies",
            filled_ports: [],
            returned_ports: ["text"],
          },
        ],
      },
    ],
  };

  const presentation: GraphPresentation = {
    viewers: [
      {
        id: "doc-scan",
        position: { x: 2 * CELL_SIZE, y: 4 * CELL_SIZE },
        layout: {
          width: 8 * CELL_SIZE,
          body_height: 6 * CELL_SIZE,
          appendix_height: null,
        },
        mode: "artifact",
        artifact_ref: {
          artifact_id: "invoice-scan-1",
          artifact_type: IMAGE,
          schema_version: 1,
        },
      },
    ],
    links: [],
    bindings: [],
    annotations: [
      {
        id: "frame-ingest",
        kind: "rectangle",
        position: { x: 1 * CELL_SIZE, y: 1 * CELL_SIZE },
        layout: { width: 26 * CELL_SIZE, height: 26 * CELL_SIZE },
        text: "Document Ingestion & OCR",
        color: "#0369a1",
      },
      {
        id: "note-hint",
        kind: "text",
        position: { x: 32 * CELL_SIZE, y: 16 * CELL_SIZE },
        layout: { width: 12 * CELL_SIZE, height: 6 * CELL_SIZE },
        text: "Driven by AuthoredGraphDocument + normalized commands + live node registry.",
        color: "#b45309",
      },
    ],
  };

  const nodeRunState: Record<string, CellNodeRunState> = {
    "ocr-extract": {
      status: "done",
      statusLabel: "240 ms",
      appendix: {
        title: "Extracted markdown",
        kindBadge: "Text value",
        heightCells: 4,
        summaryText: "240 tokens · 2 tables",
        itemCount: 2,
        previewLines: ["# INVOICE #4092", "| Item | Qty | Net |"],
      },
    },
    "page-batch": { status: "done" },
    summarize: { status: "done", statusLabel: "110 ms" },
  };

  return { document, presentation, nodeRunState };
}
