import { createUuid } from "@/features/workbench/model/uuid";
export const SCHEMA_BUILDER_OPERATOR_ID = "schema.builder";
export const SCHEMA_BUILDER_INPUT_PORT = "schemas";

export const SCHEMA_FIELD_KINDS = [
  "string",
  "integer",
  "number",
  "boolean",
  "sequence",
  "schema",
] as const;

export const SCHEMA_SEQUENCE_ITEM_KINDS = [
  "string",
  "integer",
  "number",
  "boolean",
  "schema",
] as const;

export type SchemaFieldKind = (typeof SCHEMA_FIELD_KINDS)[number];
export type SchemaSequenceItemKind =
  (typeof SCHEMA_SEQUENCE_ITEM_KINDS)[number];

export interface SchemaBuilderField {
  id: string;
  name: string;
  kind: SchemaFieldKind;
  required: boolean;
  description: string;
  item_kind?: SchemaSequenceItemKind;
}

function objectRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function isSchemaFieldKind(value: unknown): value is SchemaFieldKind {
  return SCHEMA_FIELD_KINDS.some((kind) => kind === value);
}

function isSchemaSequenceItemKind(
  value: unknown,
): value is SchemaSequenceItemKind {
  return SCHEMA_SEQUENCE_ITEM_KINDS.some((kind) => kind === value);
}

/** Reads the persisted config without manufacturing unstable field identities. */
export function schemaBuilderFields(value: unknown): SchemaBuilderField[] {
  if (!Array.isArray(value)) return [];

  const seenIds = new Set<string>();
  const fields: SchemaBuilderField[] = [];
  for (const item of value) {
    const field = objectRecord(item);
    if (
      !field ||
      typeof field.id !== "string" ||
      !field.id ||
      seenIds.has(field.id) ||
      typeof field.name !== "string" ||
      !isSchemaFieldKind(field.kind) ||
      typeof field.required !== "boolean" ||
      typeof field.description !== "string"
    ) {
      continue;
    }

    if (field.kind === "sequence") {
      if (!isSchemaSequenceItemKind(field.item_kind)) continue;
      fields.push({
        id: field.id,
        name: field.name,
        kind: field.kind,
        required: field.required,
        description: field.description,
        item_kind: field.item_kind,
      });
    } else {
      fields.push({
        id: field.id,
        name: field.name,
        kind: field.kind,
        required: field.required,
        description: field.description,
      });
    }
    seenIds.add(field.id);
  }
  return fields;
}

export function createSchemaBuilderField(
  index: number,
  id: string = createUuid(),
): SchemaBuilderField {
  return {
    id,
    name: `field_${index + 1}`,
    kind: "string",
    required: false,
    description: "",
  };
}

export function schemaFieldConsumesInput(field: SchemaBuilderField): boolean {
  return (
    field.kind === "schema" ||
    (field.kind === "sequence" && field.item_kind === "schema")
  );
}

export function withSchemaFieldKind(
  field: SchemaBuilderField,
  kind: SchemaFieldKind,
): SchemaBuilderField {
  if (kind === "sequence") {
    return { ...field, kind, item_kind: "string" };
  }
  return {
    id: field.id,
    name: field.name,
    kind,
    required: field.required,
    description: field.description,
  };
}

export function moveSchemaBuilderField(
  fields: readonly SchemaBuilderField[],
  fieldId: string,
  toIndex: number,
): SchemaBuilderField[] {
  const fromIndex = fields.findIndex((field) => field.id === fieldId);
  if (fromIndex === -1 || fields.length < 2) return [...fields];

  const boundedIndex = Math.max(0, Math.min(toIndex, fields.length - 1));
  if (fromIndex === boundedIndex) return [...fields];

  const reordered = [...fields];
  const [movedField] = reordered.splice(fromIndex, 1);
  reordered.splice(boundedIndex, 0, movedField);
  return reordered;
}
