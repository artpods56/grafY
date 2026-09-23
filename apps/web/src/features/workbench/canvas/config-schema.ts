interface SchemaFieldBase {
  name: string;
  title: string;
  description?: string;
  enumValues?: readonly (string | number)[];
  format?: "textarea";
  codeLanguage?: "sql";
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  required: boolean;
  nullable: boolean;
}

export interface ScalarSchemaField extends SchemaFieldBase {
  type: "string" | "integer" | "number" | "boolean";
}

export interface NumberTupleItem {
  title: string;
  type: "integer" | "number";
  minimum?: number;
  maximum?: number;
}

export interface NumberTupleSchemaField extends SchemaFieldBase {
  type: "number-tuple";
  items: readonly NumberTupleItem[];
}

export interface StringListSchemaField extends SchemaFieldBase {
  type: "string-list";
  minItems?: number;
  maxItems?: number;
  itemMinLength?: number;
  itemMaxLength?: number;
  itemPattern?: string;
}

export type SchemaField =
  ScalarSchemaField | NumberTupleSchemaField | StringListSchemaField;

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function resolveSchema(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): Record<string, unknown> {
  const reference = schema.$ref;
  if (typeof reference !== "string" || !reference.startsWith("#/$defs/")) {
    return schema;
  }
  const name = reference.slice("#/$defs/".length);
  const definitions = record(root.$defs);
  return record(definitions?.[name]) ?? schema;
}

function editableSchema(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): { schema: Record<string, unknown>; nullable: boolean } {
  const resolved = resolveSchema(schema, root);
  if (!Array.isArray(resolved.anyOf)) {
    return { schema: resolved, nullable: false };
  }
  if (resolved.anyOf.length !== 2) {
    return { schema: resolved, nullable: false };
  }

  const branches = resolved.anyOf
    .map(record)
    .filter((branch): branch is Record<string, unknown> => branch !== null);
  const nullBranches = branches.filter((branch) => branch.type === "null");
  const valueBranches = branches.filter((branch) => branch.type !== "null");
  if (
    branches.length !== 2 ||
    nullBranches.length !== 1 ||
    valueBranches.length !== 1
  ) {
    return { schema: resolved, nullable: false };
  }
  return {
    schema: resolveSchema(valueBranches[0], root),
    nullable: true,
  };
}

function fixedNumberTupleItems(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): NumberTupleItem[] | null {
  if (
    schema.type !== "array" ||
    !Array.isArray(schema.prefixItems) ||
    !Number.isInteger(schema.minItems) ||
    !Number.isInteger(schema.maxItems) ||
    schema.minItems !== schema.maxItems ||
    schema.minItems !== schema.prefixItems.length ||
    schema.prefixItems.length === 0
  ) {
    return null;
  }

  const items: NumberTupleItem[] = [];
  for (const [index, rawItem] of schema.prefixItems.entries()) {
    const itemRecord = record(rawItem);
    if (!itemRecord) return null;
    const item = resolveSchema(itemRecord, root);
    if (item.type !== "number" && item.type !== "integer") return null;
    items.push({
      title: typeof item.title === "string" ? item.title : `Value ${index + 1}`,
      type: item.type,
      minimum: typeof item.minimum === "number" ? item.minimum : undefined,
      maximum: typeof item.maximum === "number" ? item.maximum : undefined,
    });
  }
  return items;
}

function stringListConstraints(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): Omit<StringListSchemaField, keyof SchemaFieldBase | "type"> | null {
  if (schema.type !== "array") return null;
  const rawItems = record(schema.items);
  if (!rawItems) return null;
  const items = resolveSchema(rawItems, root);
  if (items.type !== "string") return null;

  return {
    minItems: typeof schema.minItems === "number" ? schema.minItems : undefined,
    maxItems: typeof schema.maxItems === "number" ? schema.maxItems : undefined,
    itemMinLength:
      typeof items.minLength === "number" ? items.minLength : undefined,
    itemMaxLength:
      typeof items.maxLength === "number" ? items.maxLength : undefined,
    itemPattern: typeof items.pattern === "string" ? items.pattern : undefined,
  };
}

/** Editable scalar, string-list, and fixed-number-tuple config fields. */
export function schemaFields(rawSchema: unknown): SchemaField[] {
  const root = record(rawSchema);
  const properties = record(root?.properties);
  if (!root || !properties) return [];

  const required = new Set(
    Array.isArray(root.required)
      ? root.required.filter(
          (value): value is string => typeof value === "string",
        )
      : [],
  );

  return Object.entries(properties).flatMap(
    ([name, rawProperty]): SchemaField[] => {
      if (/api.?key|token|secret/i.test(name)) {
        return [];
      }

      const propertyRecord = record(rawProperty);
      if (!propertyRecord) return [];
      const propertyMetadata = resolveSchema(propertyRecord, root);
      const editable = editableSchema(propertyMetadata, root);
      const property = editable.schema;
      const common = {
        name,
        title:
          typeof propertyMetadata.title === "string"
            ? propertyMetadata.title
            : name.replaceAll("_", " "),
        description:
          typeof propertyMetadata.description === "string"
            ? propertyMetadata.description
            : typeof property.description === "string"
              ? property.description
              : undefined,
        required: required.has(name),
        nullable: editable.nullable,
      };
      const tupleItems = fixedNumberTupleItems(property, root);
      if (tupleItems) {
        return [
          {
            ...common,
            type: "number-tuple" as const,
            items: tupleItems,
          },
        ];
      }
      const stringList = stringListConstraints(property, root);
      if (stringList) {
        return [
          {
            ...common,
            type: "string-list" as const,
            ...stringList,
          },
        ];
      }

      const enumValues = Array.isArray(property.enum)
        ? property.enum.filter(
            (value): value is string | number =>
              typeof value === "string" || typeof value === "number",
          )
        : undefined;
      const candidateType =
        typeof property.type === "string"
          ? property.type
          : enumValues?.every((value) => typeof value === "number")
            ? "number"
            : enumValues?.length
              ? "string"
              : null;
      if (
        candidateType !== "string" &&
        candidateType !== "integer" &&
        candidateType !== "number" &&
        candidateType !== "boolean"
      ) {
        return [];
      }

      return [
        {
          ...common,
          type: candidateType,
          enumValues,
          format: property.format === "textarea" ? "textarea" : undefined,
          codeLanguage:
            property.contentMediaType === "application/sql" ? "sql" : undefined,
          minimum:
            typeof property.minimum === "number" ? property.minimum : undefined,
          maximum:
            typeof property.maximum === "number" ? property.maximum : undefined,
          minLength:
            typeof property.minLength === "number"
              ? property.minLength
              : undefined,
          maxLength:
            typeof property.maxLength === "number"
              ? property.maxLength
              : undefined,
          pattern:
            typeof property.pattern === "string" ? property.pattern : undefined,
        },
      ];
    },
  );
}
