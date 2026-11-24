/**
 * How an operator card's config band is laid out on the cell lattice, from
 * the node's config schema and stored values alone.
 *
 * Every control the band draws sits on whole 25px dense rows, nested ones
 * included: a composite field is a header row plus its children's rows, never
 * a measured box. So the adapter can count the band's rows before anything
 * renders, the card grows by whole cells when a section opens, and the ports
 * above the band never move. The renderer places each child with the same
 * numbers it was counted with, which is what keeps the count honest.
 */
import {
  buildDefaultForField,
  fieldDisplayTitle,
  visibleSchemaFields,
  type ConfigValidationIssue,
  type ConnectedInputPortMap,
  type DiscriminatedUnionBranch,
  type DiscriminatedUnionSchemaField,
  type ObjectListSchemaField,
  type ObjectSchemaField,
  type SchemaField,
  type StringListSchemaField,
} from "../config-ui/config-schema";
import {
  HALF_WIDTH_CELLS,
  configControlKind,
  fieldFootprint,
  type ConfigControlKind,
} from "../config-ui/field-footprints";

import type {
  CellConfigFieldKind,
  CellConfigFieldSpec,
} from "./cell-contracts";

/** The section key of the row that folds untouched advanced fields away. */
export const ADVANCED_SECTION_KEY = "advanced";

/**
 * The fold's title. It names the section, so it reads the same opened and
 * closed; `aria-expanded` carries the state instead of the wording.
 */
export const ADVANCED_SECTION_LABEL = "Advanced";

/** Config field names are identifiers, so a colon never collides with one. */
export const ADVANCED_TOGGLE_ID = ":advanced";

export function groupSectionKey(name: string): string {
  return `group:${name}`;
}

/** An object field's fold, by its path from the config root (`style.fill`). */
export function objectSectionKey(path: string): string {
  return `object:${path}`;
}

export function childPath(parent: string, name: string | number): string {
  return `${parent}.${name}`;
}

/** A section the person opened or closed keeps that; any other its default. */
export function sectionOpen(
  sections: Readonly<Record<string, boolean>> | undefined,
  key: string,
  fallback: boolean,
): boolean {
  return sections?.[key] ?? fallback;
}

// --- Shelves ----------------------------------------------------------------

export interface ShelfItem {
  /** 1 takes one of the shelf's two columns, 2 the whole shelf. */
  span: 1 | 2;
  rows: number;
}

export interface ShelfPlacement {
  /** First dense row, counted from 0. */
  row: number;
  /** 1 or 2 for a half-width item; `null` for one across the shelf. */
  column: 1 | 2 | null;
  /**
   * Rows of the grid area the item occupies: its own rows, except on a shared
   * shelf, where it is the whole shelf. A control shorter than its shelf gets
   * the area either way, which is what lets the renderer stand it on the
   * shelf's bottom instead of floating it beside its neighbour's label.
   */
  rows: number;
}

/**
 * Two half-width items share a shelf as tall as the taller one; a full-width
 * item, or a half-width one with no partner, takes a shelf of its own.
 */
export function placeShelves(items: readonly ShelfItem[]): {
  placements: ShelfPlacement[];
  totalRows: number;
} {
  const placements: ShelfPlacement[] = [];
  let row = 0;
  let pending: { index: number; rows: number } | null = null;
  for (const item of items) {
    const rows = Math.max(1, item.rows);
    if (item.span === 1) {
      if (pending === null) {
        const index = placements.length;
        placements.push({ row, column: 1, rows });
        pending = { index, rows };
        continue;
      }
      const shelfRows = Math.max(pending.rows, rows);
      const first = placements[pending.index];
      if (first) first.rows = shelfRows;
      placements.push({ row, column: 2, rows: shelfRows });
      row += shelfRows;
      pending = null;
      continue;
    }
    if (pending !== null) {
      row += pending.rows;
      pending = null;
    }
    placements.push({ row, column: null, rows });
    row += rows;
  }
  if (pending !== null) row += pending.rows;
  return { placements, totalRows: row };
}

// --- Values a composite field draws --------------------------------------------

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** Layout never mints ids; only an edit writes a new item. */
const PLAN_ID = () => "plan";

/** A schema default, or one built from the object's own field defaults. */
export function objectDefault(
  field: ObjectSchemaField,
  generateId?: () => string,
): Record<string, unknown> {
  return (
    record(buildDefaultForField(field, { generateId })) ??
    record(
      buildDefaultForField(
        { ...field, defaultValue: undefined, examples: undefined },
        { generateId },
      ),
    ) ?? { ...field.constFields }
  );
}

/**
 * What an object field holds: an optional group the person switched off is
 * `null`, and anything else draws its stored object over its defaults.
 */
export function objectFieldState(
  field: ObjectSchemaField,
  value: unknown,
): { enabled: boolean; base: Record<string, unknown> } {
  const current = record(value === undefined ? field.defaultValue : value);
  return {
    enabled: !field.nullable || current !== null,
    base: current ?? objectDefault(field, PLAN_ID),
  };
}

function branchObjectField(
  field: DiscriminatedUnionSchemaField,
  branch: DiscriminatedUnionBranch,
): ObjectSchemaField {
  return {
    type: "object",
    name: field.name,
    title: branch.label,
    required: true,
    nullable: false,
    fields: branch.fields,
    constFields: branch.constFields,
    ...(branch.autoIdFields ? { autoIdFields: branch.autoIdFields } : {}),
  };
}

/** The value a union takes when the person switches to `branch`. */
export function branchDefault(
  field: DiscriminatedUnionSchemaField,
  branch: DiscriminatedUnionBranch,
  generateId?: () => string,
): Record<string, unknown> {
  const declared = record(field.defaultValue);
  if (declared?.[field.discriminator] === branch.tag) {
    return structuredClone(declared);
  }
  return (
    record(
      buildDefaultForField(branchObjectField(field, branch), { generateId }),
    ) ?? { ...branch.constFields }
  );
}

/** The branch a union value is on, and the value its fields draw from. */
export function unionFieldState(
  field: DiscriminatedUnionSchemaField,
  value: unknown,
): { branch: DiscriminatedUnionBranch; base: Record<string, unknown> } | null {
  const current =
    record(value) ??
    record(buildDefaultForField(field, { generateId: PLAN_ID }));
  const activeTag = current?.[field.discriminator];
  const branch =
    field.branches.find((candidate) => candidate.tag === activeTag) ??
    field.branches[0];
  if (!branch) return null;
  const base =
    current?.[field.discriminator] === branch.tag
      ? current
      : branchDefault(field, branch, PLAN_ID);
  return { branch, base };
}

export function stringListValues(
  field: StringListSchemaField,
  value: unknown,
): string[] {
  const source = value === undefined ? field.defaultValue : value;
  return Array.isArray(source) &&
    source.every((item): item is string => typeof item === "string")
    ? source
    : [];
}

export function objectListItems(
  field: ObjectListSchemaField,
  value: unknown,
): Record<string, unknown>[] {
  const source = Array.isArray(value)
    ? value
    : buildDefaultForField(field, { generateId: PLAN_ID });
  return (Array.isArray(source) ? source : []).map(
    (item) => record(item) ?? {},
  );
}

/** An item list's `title` field heads each item instead of sitting in it. */
export function objectListTitleField(
  field: ObjectListSchemaField,
): SchemaField | undefined {
  return field.itemFields.find(
    (child) =>
      child.name === "title" && child.type === "string" && !child.enumValues,
  );
}

/** "GeoPointCategory" → "Category": the noun a list adds one of. */
export function objectListItemNoun(field: ObjectListSchemaField): string {
  if (!/^(?:[A-Z][a-z0-9]+){2,}$/.test(field.itemTitle)) return field.itemTitle;
  return field.itemTitle.match(/[A-Z][a-z0-9]+$/)?.[0] ?? field.itemTitle;
}

/**
 * A new item's title, numbered, wherever the schema's default would read as
 * nothing: unset, empty, the schema's one example every item would share, or
 * the `minLength` filler a default is built with.
 */
export function titledNewItem(
  field: ObjectListSchemaField,
  item: Record<string, unknown>,
  index: number,
): Record<string, unknown> {
  const titleField = objectListTitleField(field);
  if (!titleField) return item;
  const filler =
    titleField.minLength !== undefined && titleField.minLength > 0
      ? "a".repeat(titleField.minLength)
      : "";
  const title = item.title;
  const placeholder =
    title === undefined ||
    title === "" ||
    title === filler ||
    sameJson(title, titleField.examples?.[0]);
  return placeholder
    ? { ...item, title: `${objectListItemNoun(field)} ${index + 1}` }
    : item;
}

/** A branch's fresh value with every list it starts with titled per item. */
export function titledBranchValue(
  branch: DiscriminatedUnionBranch,
  value: Record<string, unknown>,
): Record<string, unknown> {
  const next = { ...value };
  for (const field of branch.fields) {
    if (field.type !== "object-list") continue;
    const items = next[field.name];
    if (!Array.isArray(items)) continue;
    next[field.name] = items.map((item, index) =>
      titledNewItem(field, record(item) ?? {}, index),
    );
  }
  return next;
}

// --- Rows ---------------------------------------------------------------------

export interface ConfigRowContext {
  sections?: Readonly<Record<string, boolean>>;
  connectedPorts?: ConnectedInputPortMap;
}

/** Dense rows a scalar control takes: its label row, then the control. */
const SCALAR_ROWS: Partial<Record<ConfigControlKind, number>> = {
  // A switch or checkbox carries its label beside it.
  checkbox: 1,
  switch: 1,
  textarea: 4,
};
const LABELLED_CONTROL_ROWS = 2;

/** Wide kinds take a whole shelf; compact ones pair up. */
export function schemaFieldSpan(field: SchemaField): 1 | 2 {
  return fieldFootprint(field).columns > HALF_WIDTH_CELLS ? 2 : 1;
}

/** The children of a composite field a value shows, in schema order. */
export function visibleNestedFields(
  fields: readonly SchemaField[],
  value: Readonly<Record<string, unknown>>,
  connectedPorts: ConnectedInputPortMap | undefined,
): SchemaField[] {
  return visibleSchemaFields(fields, { config: value, connectedPorts });
}

/** Where each visible child of a composite field sits, and how tall they are. */
export function nestedFieldPlan(
  fields: readonly SchemaField[],
  value: Readonly<Record<string, unknown>>,
  path: string,
  context: ConfigRowContext,
): {
  fields: SchemaField[];
  placements: ShelfPlacement[];
  totalRows: number;
} {
  const visible = visibleNestedFields(fields, value, context.connectedPorts);
  const { placements, totalRows } = placeShelves(
    visible.map((child) => ({
      span: schemaFieldSpan(child),
      rows: schemaFieldDenseRows(
        child,
        value[child.name],
        childPath(path, child.name),
        context,
      ),
    })),
  );
  return { fields: visible, placements, totalRows };
}

/**
 * Dense rows one schema field takes on the lattice, nested fields and open
 * sections included. `path` names the field from the config root, so a
 * nested object's fold is told apart from another one's.
 */
export function schemaFieldDenseRows(
  field: SchemaField,
  value: unknown,
  path: string,
  context: ConfigRowContext,
): number {
  switch (field.type) {
    case "number-tuple":
      // Its title, then two inline-labelled values a row.
      return 1 + Math.max(1, Math.ceil(field.items.length / 2));
    case "string-list":
      // Its title, one row an item, and the "Add item" row.
      return 1 + stringListValues(field, value).length + 1;
    case "primitive-list":
      return LABELLED_CONTROL_ROWS;
    case "object": {
      const { enabled, base } = objectFieldState(field, value);
      const open = field.nullable
        ? enabled
        : sectionOpen(context.sections, objectSectionKey(path), false);
      if (!open) return 1;
      return 1 + nestedFieldPlan(field.fields, base, path, context).totalRows;
    }
    case "discriminated-union": {
      const state = unionFieldState(field, value);
      if (!state) return 1;
      return (
        1 +
        nestedFieldPlan(state.branch.fields, state.base, path, context)
          .totalRows
      );
    }
    case "object-list": {
      const titleField = objectListTitleField(field);
      const bodyFields = field.itemFields.filter(
        (child) => child !== titleField,
      );
      let rows = 1;
      objectListItems(field, value).forEach((item, index) => {
        rows +=
          1 +
          nestedFieldPlan(bodyFields, item, childPath(path, index), context)
            .totalRows;
      });
      // The "Add" row.
      return rows + 1;
    }
  }
  return SCALAR_ROWS[configControlKind(field)] ?? LABELLED_CONTROL_ROWS;
}

// --- The top-level band ---------------------------------------------------------

type ConfigSegment =
  | { kind: "board"; fields: SchemaField[] }
  | { kind: "group"; name: string; fields: SchemaField[] };

/**
 * Ungrouped fields stay in schema order; a named group gathers its fields
 * where its first one stands, so the card reads in the order the schema does.
 */
function configSegments(fields: readonly SchemaField[]): ConfigSegment[] {
  const segments: ConfigSegment[] = [];
  const groups = new Map<string, SchemaField[]>();
  for (const field of fields) {
    if (field.group) {
      const members = groups.get(field.group);
      if (members) {
        members.push(field);
        continue;
      }
      const created = [field];
      groups.set(field.group, created);
      segments.push({ kind: "group", name: field.group, fields: created });
      continue;
    }
    const last = segments.at(-1);
    if (last?.kind === "board") {
      last.fields.push(field);
    } else {
      segments.push({ kind: "board", fields: [field] });
    }
  }
  return segments;
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** An advanced field folds away only while it still holds its default. */
function isQuietAdvanced(
  field: SchemaField,
  value: unknown,
  invalidFields: ReadonlySet<string | null>,
): boolean {
  if (!field.advanced || invalidFields.has(field.name)) return false;
  return value === undefined || sameJson(value, field.defaultValue);
}

/** A group opens by default when it holds something to fix or to set. */
function groupStartsOpen(
  fields: readonly SchemaField[],
  invalidFields: ReadonlySet<string | null>,
): boolean {
  return fields.some(
    (field) => invalidFields.has(field.name) || !field.advanced,
  );
}

/**
 * The fields the `Advanced` row discloses: the loose ones marked advanced. A
 * named group is a container of its own already, so its advanced members stay
 * with it instead of moving under the fold.
 */
function advancedFoldFields(fields: readonly SchemaField[]): SchemaField[] {
  return fields.filter((field) => field.advanced && !field.group);
}

const COARSE_KINDS: Record<ConfigControlKind, CellConfigFieldKind> = {
  text: "text",
  number: "number",
  select: "select",
  checkbox: "toggle",
  textarea: "multiline",
  slider: "number",
  color: "text",
  segmented: "select",
  switch: "toggle",
  "number-tuple": "text",
  "string-list": "multiline",
  "primitive-list": "multiline",
  object: "multiline",
  "discriminated-union": "multiline",
  "object-list": "multiline",
  secret: "text",
};

/** The primitive a simple control would show for a stored value. */
function primitiveFace(
  saved: unknown,
  kind: CellConfigFieldKind,
): string | number | boolean {
  if (
    typeof saved === "string" ||
    typeof saved === "number" ||
    typeof saved === "boolean"
  ) {
    return saved;
  }
  if (saved !== null && typeof saved === "object") return JSON.stringify(saved);
  return kind === "toggle" ? false : kind === "number" ? 0 : "";
}

function schemaEntry(
  field: SchemaField,
  config: Readonly<Record<string, unknown>>,
  context: ConfigRowContext,
  issue: string | undefined,
): CellConfigFieldSpec {
  const kind = COARSE_KINDS[configControlKind(field)];
  const saved = config[field.name];
  return {
    id: field.name,
    label: fieldDisplayTitle(field),
    kind,
    value: primitiveFace(saved, kind),
    ...(field.enumValues
      ? {
          options: field.enumValues.map((option) => ({
            value: String(option),
            label: field.enumLabels?.[String(option)] ?? String(option),
          })),
        }
      : {}),
    span: schemaFieldSpan(field),
    denseRows: schemaFieldDenseRows(field, saved, field.name, context),
    schemaField: field,
    rawValue: saved,
    ...(issue ? { issue } : {}),
  };
}

/**
 * The rows of a node's config band, in order: its visible fields, the header
 * of each named group, the `Advanced` row with the advanced fields it heads,
 * and a notice for issues no shown field can display. A field hidden by its
 * `visibleWhen` takes no row at all, unless it holds an issue to fix.
 *
 * The `Advanced` row is emitted before the fields it discloses, opened or
 * closed, so the header stays at the head of its group instead of dropping
 * below the fields the click revealed. An advanced field the person changed,
 * or one with something to fix, is never folded away: it shows under the row
 * while the rest stay hidden.
 */
export function buildSchemaConfigEntries({
  fields,
  config,
  issues = [],
  connectedPorts,
  sections,
}: {
  fields: readonly SchemaField[];
  config: Readonly<Record<string, unknown>>;
  issues?: readonly ConfigValidationIssue[];
  connectedPorts?: ConnectedInputPortMap;
  sections?: Readonly<Record<string, boolean>>;
}): CellConfigFieldSpec[] {
  const context: ConfigRowContext = { sections, connectedPorts };
  const visible = visibleSchemaFields(
    fields,
    { config, connectedPorts },
    issues,
  );
  const invalidFields = new Set(issues.map((issue) => issue.fieldName));
  const issueByField = new Map<string, string>();
  for (const issue of issues) {
    if (issue.fieldName !== null && !issueByField.has(issue.fieldName)) {
      issueByField.set(issue.fieldName, issue.message);
    }
  }
  // The row counts the loose advanced fields, which are exactly the ones its
  // fold holds. A named group is a container of its own, so a field it carries
  // stays with the group instead of being counted here and shown nowhere.
  const foldable = advancedFoldFields(visible);
  const quietFold = foldable.filter((field) =>
    isQuietAdvanced(field, config[field.name], invalidFields),
  );
  const quietAdvanced = new Set(quietFold);
  const advancedOpen = sectionOpen(sections, ADVANCED_SECTION_KEY, false);
  const fold = quietFold.length > 0 ? foldable : [];
  const inFold = new Set(fold);
  const foldShown = advancedOpen
    ? fold
    : fold.filter((field) => !quietAdvanced.has(field));
  const shown = visible.filter(
    (field) =>
      !inFold.has(field) && (advancedOpen || !quietAdvanced.has(field)),
  );

  const entries: CellConfigFieldSpec[] = [];
  for (const segment of configSegments(shown)) {
    if (segment.kind === "group") {
      const key = groupSectionKey(segment.name);
      const open = sectionOpen(
        sections,
        key,
        groupStartsOpen(segment.fields, invalidFields),
      );
      entries.push({
        id: key,
        label: segment.name,
        kind: "group",
        value: "",
        span: 2,
        denseRows: 1,
        section: {
          key,
          open,
          count: segment.fields.length,
          issueCount: segment.fields.filter((field) =>
            issueByField.has(field.name),
          ).length,
        },
      });
      if (!open) continue;
    }
    for (const field of segment.fields) {
      entries.push(
        schemaEntry(field, config, context, issueByField.get(field.name)),
      );
    }
  }

  if (quietAdvanced.size > 0) {
    entries.push({
      id: ADVANCED_TOGGLE_ID,
      label: ADVANCED_SECTION_LABEL,
      kind: "advanced",
      value: "",
      span: 2,
      denseRows: 1,
      section: {
        key: ADVANCED_SECTION_KEY,
        open: advancedOpen,
        count: quietAdvanced.size,
        issueCount: 0,
      },
    });
    for (const field of foldShown) {
      entries.push(
        schemaEntry(field, config, context, issueByField.get(field.name)),
      );
    }
  }

  const shownNames = new Set(
    [...shown, ...foldShown].map((field) => field.name),
  );
  const unshownIssues = issues.filter(
    (issue) => issue.fieldName === null || !shownNames.has(issue.fieldName),
  );
  if (unshownIssues.length > 0) {
    entries.push({
      id: ":issues",
      label:
        unshownIssues.length === 1
          ? (unshownIssues[0]?.message ?? "1 config issue")
          : `${unshownIssues.length} config issues this card cannot edit`,
      kind: "issues",
      value: "",
      span: 2,
      denseRows: 1,
    });
  }
  return entries;
}

// --- What the `Advanced` row heads -------------------------------------------

/** A section header ends the entries its own row heads. */
const GROUP_STARTING_KINDS: ReadonlySet<CellConfigFieldSpec["kind"]> = new Set([
  "group",
  "advanced",
  "issues",
]);

/**
 * The entries the card's `Advanced` row discloses: the ones emitted after it,
 * up to the next header. The band frames them as one group from this alone, so
 * the frozen cross-lane contract needs no flag for a purely presentational
 * grouping. Empty when the card has nothing folded away, or nothing open.
 */
export function advancedGroupIndices(
  entries: readonly CellConfigFieldSpec[],
): number[] {
  const toggle = entries.findIndex((entry) => entry.id === ADVANCED_TOGGLE_ID);
  if (toggle < 0) return [];
  const indices: number[] = [];
  for (let index = toggle + 1; index < entries.length; index += 1) {
    const entry = entries[index];
    if (!entry || GROUP_STARTING_KINDS.has(entry.kind)) break;
    indices.push(index);
  }
  return indices;
}
