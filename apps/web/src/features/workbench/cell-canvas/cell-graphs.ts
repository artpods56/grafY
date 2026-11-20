import {
  STRIP_FIRST_PORT_ROW,
  PORT_ROW_PITCH,
  type CellCardModel,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
} from "./cell-model";

/**
 * Graphs for the cell canvas spike: a small demo that shows each routing
 * option at work, and a 60-card grid to feel the router's speed.
 */

const FILE_CSV = "file.csv";
const TABLE = "table.data";
const MARKDOWN = "text.markdown";
const IMAGE = "image.raster";
const DATASET = "export.dataset";

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
  return { id, sourceCardId, sourcePortId, targetCardId, targetPortId };
}

/**
 * Four cards. The table list feeds Summarize and Publish through the gutter
 * at columns 13–16 (twin pipes side by side); the report doubles back to
 * Render through the horizontal gutter at rows 11–12, and feeds Publish below
 * Summarize, where free exits drop cleanly into the gutter instead of looping.
 */
export function createDemoCellGraph(): CellGraph {
  const cards: CellCardModel[] = [
    {
      id: "import",
      title: "Import tables",
      subtitle: "CSV → list",
      status: "done",
      col: 0,
      row: 0,
      widthCells: 12,
      heightCells: 6,
      ports: [
        input("file", 2, FILE_CSV, "one", true),
        output("tables", 2, TABLE, "many"),
      ],
    },
    {
      id: "summarize",
      title: "Summarize tables",
      subtitle: "Aggregate rows",
      status: "done",
      col: 18,
      row: 4,
      widthCells: 12,
      heightCells: 6,
      ports: [
        input("tables", 2, TABLE, "many", true),
        output("report", 2, MARKDOWN, "one"),
      ],
    },
    {
      id: "render",
      title: "Render page",
      subtitle: "Markdown → HTML",
      status: "idle",
      col: 0,
      row: 12,
      widthCells: 12,
      heightCells: 6,
      ports: [
        input("body", 2, MARKDOWN, "one", true),
        input("logo", 4, IMAGE, "one", false),
      ],
    },
    {
      id: "publish",
      title: "Publish bundle",
      subtitle: "Export dataset",
      status: "idle",
      col: 18,
      row: 12,
      widthCells: 12,
      heightCells: 6,
      ports: [
        input("tables", 2, TABLE, "many", true),
        input("report", 4, MARKDOWN, "one", true),
        output("bundle", 2, DATASET, "one"),
      ],
    },
  ];
  const pipes = [
    pipe("pipe-tables", ["import", "tables"], ["summarize", "tables"]),
    pipe("pipe-report", ["summarize", "report"], ["render", "body"]),
    pipe("pipe-tables-pub", ["import", "tables"], ["publish", "tables"]),
    pipe("pipe-report-pub", ["summarize", "report"], ["publish", "report"]),
  ];
  return { cards, pipes };
}

const STRESS_COLUMNS = 10;
const STRESS_ROWS = 6;
const STRESS_CARD_WIDTH = 12;
const STRESS_CARD_HEIGHT = 8;
/** One port column, four gutter columns, one port column between cards. */
const STRESS_STEP_COL = 18;
/** Four gutter rows between cards. */
const STRESS_STEP_ROW = 12;

function isImporter(row: number, column: number): boolean {
  return (row + column) % 3 === 0;
}

/**
 * Sixty cards in a 10 × 6 grid. Each is fed by its left neighbour and both
 * upper diagonals, so a third of the 144 pipes double back.
 */
export function createStressCellGraph(): CellGraph {
  const cards: CellCardModel[] = [];
  const pipes: CellPipeModel[] = [];
  for (let row = 0; row < STRESS_ROWS; row += 1) {
    for (let column = 0; column < STRESS_COLUMNS; column += 1) {
      const id = `stress-${row}-${column}`;
      const imports = isImporter(row, column);
      const feeds: [string, number, number][] = [
        ["left", column - 1, row],
        ["up-left", column - 1, row - 1],
        ["up-right", column + 1, row - 1],
      ];
      const inputPorts = feeds.map(([name, fromColumn, fromRow], slot) => {
        const hasFeeder =
          fromColumn >= 0 && fromRow >= 0 && fromColumn < STRESS_COLUMNS;
        const fromImporter = hasFeeder
          ? isImporter(fromRow, fromColumn)
          : slot === 0;
        return input(
          name,
          STRIP_FIRST_PORT_ROW + slot * PORT_ROW_PITCH,
          fromImporter ? TABLE : MARKDOWN,
          fromImporter ? "many" : "one",
        );
      });
      cards.push({
        id,
        title: imports ? "Import tables" : "Summarize tables",
        subtitle: imports ? "CSV → list" : "Aggregate rows",
        status: "idle",
        col: column * STRESS_STEP_COL,
        row: row * STRESS_STEP_ROW,
        widthCells: STRESS_CARD_WIDTH,
        heightCells: STRESS_CARD_HEIGHT,
        ports: [
          ...inputPorts,
          imports
            ? output("out", STRIP_FIRST_PORT_ROW, TABLE, "many")
            : output("out", STRIP_FIRST_PORT_ROW, MARKDOWN, "one"),
        ],
      });
      for (const [name, fromColumn, fromRow] of feeds) {
        if (fromColumn < 0 || fromRow < 0 || fromColumn >= STRESS_COLUMNS) {
          continue;
        }
        pipes.push(
          pipe(
            `stress-pipe-${id}-${name}`,
            [`stress-${fromRow}-${fromColumn}`, "out"],
            [id, name],
          ),
        );
      }
    }
  }
  return { cards, pipes };
}
