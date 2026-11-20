import type { CellCardSurfaceData } from "@/features/workbench/cell-canvas/cell-contracts";
import { createStressCellGraph } from "@/features/workbench/cell-canvas/cell-graphs";
import type {
  CellCardModel,
  CellGraph,
  CellPipeModel,
  CellPort,
} from "@/features/workbench/cell-canvas/cell-model";

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

export function createRealAnatomyShowcaseGraph(): RealAnatomyShowcaseGraph {
  const cards: CellCardModel[] = [
    {
      id: "frame-ingest",
      title: "Document Ingestion & OCR",
      subtitle: "Docked stage",
      kind: "annotation",
      status: "idle",
      col: 1,
      row: 0,
      widthCells: 13,
      heightCells: 13,
      ports: [],
      resizable: true,
      resizeBounds: { minWidthCells: 8, minHeightCells: 6 },
    },
    {
      id: "doc-scan",
      title: "Invoice Scan",
      subtitle: "PNG · 1600 × 1200",
      kind: "artifact",
      status: "done",
      col: 2,
      row: 1,
      widthCells: 5,
      heightCells: 3,
      ports: [output("image", 2, IMAGE, "one")],
    },
    {
      id: "ocr-extract",
      title: "Extract Invoice",
      subtitle: "Image → Text",
      kind: "operator",
      status: "done",
      col: 7,
      row: 2,
      widthCells: 6,
      heightCells: 10,
      resizable: true,
      resizeBounds: {
        minWidthCells: 6,
        maxWidthCells: 10,
        minHeightCells: 9,
        maxHeightCells: 14,
      },
      ports: [
        input("source", 1, IMAGE, "one", true),
        input("extra_hints::plug-1", 3, MARKDOWN, "one"),
        input("extra_hints::plug-2", 4, MARKDOWN, "one"),
        output("text", 1, MARKDOWN, "one"),
        output("pages", 2, TABLE, "many"),
      ],
    },
    {
      id: "page-batch",
      title: "Page Tables",
      subtitle: "Collection · 2 items",
      kind: "collection",
      status: "done",
      col: 16,
      row: 2,
      widthCells: 5,
      heightCells: 4,
      ports: [
        input("items::plug-1", 1, TABLE, "many"),
        input("items::plug-2", 2, TABLE, "many"),
        output("items", 1, TABLE, "many"),
      ],
    },
    {
      id: "summarize",
      title: "Reconcile Totals",
      subtitle: "Table → Summary",
      kind: "operator",
      status: "done",
      col: 24,
      row: 2,
      widthCells: 6,
      heightCells: 5,
      ports: [
        input("tables", 1, TABLE, "many", true),
        input("context", 2, MARKDOWN, "one"),
        output("summary", 1, MARKDOWN, "one"),
      ],
    },
    {
      id: "reviewer-agent",
      title: "Audit Reviewer",
      subtitle: "Agent · Claude Opus 5.5",
      kind: "agent",
      status: "idle",
      col: 24,
      row: 9,
      widthCells: 7,
      heightCells: 4,
      resizable: true,
      resizeBounds: {
        minWidthCells: 6,
        maxWidthCells: 10,
        minHeightCells: 4,
        maxHeightCells: 8,
      },
      ports: [
        input("artifact", 1, MARKDOWN, "one", true),
        output("verdict", 1, MARKDOWN, "one"),
      ],
    },
    {
      id: "note-hint",
      title: "Seam & Projection Note",
      subtitle: "Canvas annotation",
      kind: "annotation",
      status: "idle",
      col: 16,
      row: 8,
      widthCells: 6,
      heightCells: 3,
      ports: [],
    },
  ];

  const pipes = [
    pipe("dock-scan-ocr", ["doc-scan", "image"], ["ocr-extract", "source"]),
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
        bodyText:
          "Zero-gutter docked scan-to-OCR pipeline with dynamic hint plugs.",
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
            startRowOffset: 3,
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
          heightCells: 2,
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
          "doc-scan docks flush to ocr-extract at col 7; collection-to-summarize renders a 3x1 projection pill.",
      },
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
