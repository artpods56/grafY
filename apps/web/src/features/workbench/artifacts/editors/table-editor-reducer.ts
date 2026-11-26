export const TABLE_VALUE_TYPES = [
  "text",
  "integer",
  "number",
  "decimal",
  "boolean",
  "date",
  "datetime",
  "json",
  "binary",
  "unknown",
  "mixed",
] as const;

export type TableValueType = (typeof TABLE_VALUE_TYPES)[number];

export interface TableEditorColumn {
  id: string;
  title: string;
  value_type: TableValueType;
}

export type TableEditorCell =
  | string
  | number
  | boolean
  | null
  | TableEditorCell[]
  | { readonly [key: string]: TableEditorCell };

export interface TableEditorSnapshot {
  columns: readonly TableEditorColumn[];
  rows: readonly Readonly<Record<string, TableEditorCell>>[];
}

export interface TableEditorState extends TableEditorSnapshot {
  past: readonly TableEditorSnapshot[];
  initial: TableEditorSnapshot;
}

export type TableEditorAction =
  | { type: "set-cell"; row: number; columnId: string; value: TableEditorCell }
  | { type: "add-row"; at?: number }
  | { type: "delete-row"; row: number }
  | { type: "add-column"; title?: string; value_type?: TableValueType }
  | { type: "rename-column"; columnId: string; title: string }
  | { type: "set-column-type"; columnId: string; value_type: TableValueType }
  | { type: "delete-column"; columnId: string }
  | { type: "undo" }
  | { type: "reset" };

const MAX_UNDO = 50;

export const DEFAULT_TABLE_PAYLOAD: Record<string, unknown> = {
  columns: [{ id: "column_1", title: "Column 1", value_type: "text" }],
  rows: [{ column_1: "" }],
};

export function isValueType(value: unknown): value is TableValueType {
  return (
    typeof value === "string" &&
    (TABLE_VALUE_TYPES as readonly string[]).includes(value)
  );
}

function cloneSnapshot(snapshot: TableEditorSnapshot): TableEditorSnapshot {
  return {
    columns: snapshot.columns.map((column) => ({ ...column })),
    rows: snapshot.rows.map((row) => ({ ...row })),
  };
}

function emptyRow(
  columns: readonly TableEditorColumn[],
): Record<string, TableEditorCell> {
  const row: Record<string, TableEditorCell> = {};
  for (const column of columns) row[column.id] = null;
  return row;
}

function nextColumnId(columns: readonly TableEditorColumn[]): string {
  const used = new Set(columns.map((column) => column.id));
  let index = columns.length + 1;
  let id = `column_${index}`;
  while (used.has(id)) {
    index += 1;
    id = `column_${index}`;
  }
  return id;
}

function pushPast(state: TableEditorState): readonly TableEditorSnapshot[] {
  const snapshot = {
    columns: state.columns,
    rows: state.rows,
  };
  const past = [...state.past, snapshot];
  return past.length > MAX_UNDO ? past.slice(past.length - MAX_UNDO) : past;
}

function parseCell(value: unknown): TableEditorCell {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(parseCell);
  }
  if (typeof value === "object") {
    const record: Record<string, TableEditorCell> = {};
    for (const [key, nested] of Object.entries(value)) {
      record[key] = parseCell(nested);
    }
    return record;
  }
  return null;
}

export function parseTablePayload(
  payload: Record<string, unknown>,
): TableEditorSnapshot {
  const rawColumns = Array.isArray(payload.columns) ? payload.columns : [];
  const columns: TableEditorColumn[] = [];
  const seen = new Set<string>();
  for (const [index, raw] of rawColumns.entries()) {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) continue;
    const record = raw as Record<string, unknown>;
    const id =
      typeof record.id === "string" && record.id.trim()
        ? record.id
        : `column_${index + 1}`;
    if (seen.has(id)) continue;
    seen.add(id);
    columns.push({
      id,
      title: typeof record.title === "string" ? record.title : id,
      value_type: isValueType(record.value_type) ? record.value_type : "text",
    });
  }
  const effectiveColumns =
    columns.length > 0
      ? columns
      : [{ id: "column_1", title: "Column 1", value_type: "text" as const }];
  const rawRows = Array.isArray(payload.rows) ? payload.rows : [];
  const rows = rawRows.map((raw) => {
    const source =
      typeof raw === "object" && raw !== null && !Array.isArray(raw)
        ? (raw as Record<string, unknown>)
        : {};
    const row: Record<string, TableEditorCell> = {};
    for (const column of effectiveColumns) {
      row[column.id] =
        column.id in source ? parseCell(source[column.id]) : null;
    }
    return row;
  });
  return { columns: effectiveColumns, rows };
}

export function createTableEditorState(
  payload: Record<string, unknown> = DEFAULT_TABLE_PAYLOAD,
): TableEditorState {
  const snapshot = parseTablePayload(payload);
  return {
    ...snapshot,
    past: [],
    initial: cloneSnapshot(snapshot),
  };
}

export function tableEditorPayload(
  state: TableEditorSnapshot,
): Record<string, unknown> {
  return {
    columns: state.columns.map((column) => ({
      id: column.id,
      title: column.title,
      value_type: column.value_type,
    })),
    rows: state.rows.map((row) => {
      const next: Record<string, TableEditorCell> = {};
      for (const column of state.columns) {
        next[column.id] = row[column.id] ?? null;
      }
      return next;
    }),
  };
}

export function reduceTableEditor(
  state: TableEditorState,
  action: TableEditorAction,
): TableEditorState {
  switch (action.type) {
    case "set-cell": {
      const current = state.rows[action.row];
      if (!current) return state;
      if (!(action.columnId in current)) return state;
      if (Object.is(current[action.columnId], action.value)) return state;
      return {
        ...state,
        past: pushPast(state),
        rows: state.rows.map((row, index) =>
          index === action.row
            ? { ...row, [action.columnId]: action.value }
            : row,
        ),
      };
    }
    case "add-row": {
      const at =
        action.at === undefined
          ? state.rows.length
          : Math.max(0, Math.min(state.rows.length, action.at));
      const rows = [...state.rows];
      rows.splice(at, 0, emptyRow(state.columns));
      return { ...state, past: pushPast(state), rows };
    }
    case "delete-row": {
      if (action.row < 0 || action.row >= state.rows.length) return state;
      return {
        ...state,
        past: pushPast(state),
        rows: state.rows.filter((_, index) => index !== action.row),
      };
    }
    case "add-column": {
      const id = nextColumnId(state.columns);
      const column: TableEditorColumn = {
        id,
        title: action.title?.trim() || `Column ${state.columns.length + 1}`,
        value_type: action.value_type ?? "text",
      };
      return {
        ...state,
        past: pushPast(state),
        columns: [...state.columns, column],
        rows: state.rows.map((row) => ({ ...row, [id]: null })),
      };
    }
    case "rename-column": {
      const column = state.columns.find((item) => item.id === action.columnId);
      if (!column || column.title === action.title) return state;
      return {
        ...state,
        past: pushPast(state),
        columns: state.columns.map((item) =>
          item.id === action.columnId ? { ...item, title: action.title } : item,
        ),
      };
    }
    case "set-column-type": {
      const column = state.columns.find((item) => item.id === action.columnId);
      if (!column || column.value_type === action.value_type) return state;
      return {
        ...state,
        past: pushPast(state),
        columns: state.columns.map((item) =>
          item.id === action.columnId
            ? { ...item, value_type: action.value_type }
            : item,
        ),
      };
    }
    case "delete-column": {
      if (
        state.columns.length <= 1 ||
        !state.columns.some((column) => column.id === action.columnId)
      ) {
        return state;
      }
      return {
        ...state,
        past: pushPast(state),
        columns: state.columns.filter(
          (column) => column.id !== action.columnId,
        ),
        rows: state.rows.map((row) => {
          const next = { ...row };
          delete next[action.columnId];
          return next;
        }),
      };
    }
    case "undo": {
      const previous = state.past[state.past.length - 1];
      if (!previous) return state;
      return {
        ...state,
        columns: previous.columns,
        rows: previous.rows,
        past: state.past.slice(0, -1),
      };
    }
    case "reset": {
      if (
        state.columns === state.initial.columns &&
        state.rows === state.initial.rows
      ) {
        return state;
      }
      return {
        ...state,
        ...cloneSnapshot(state.initial),
        past: [],
      };
    }
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}

export function parseCellInput(
  raw: string,
  valueType: TableValueType,
): TableEditorCell {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  switch (valueType) {
    case "integer": {
      if (!/^-?\d+$/.test(trimmed)) return raw;
      const parsed = Number(trimmed);
      return Number.isSafeInteger(parsed) ? parsed : raw;
    }
    case "number":
    case "decimal": {
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : raw;
    }
    case "boolean": {
      if (trimmed === "true") return true;
      if (trimmed === "false") return false;
      return raw;
    }
    case "json": {
      try {
        return parseCell(JSON.parse(raw) as unknown);
      } catch {
        return raw;
      }
    }
    default:
      return raw;
  }
}

export function formatCellInput(value: TableEditorCell): string {
  if (value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}
