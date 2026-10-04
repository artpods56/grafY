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

export interface ConfigValidationIssue {
  fieldName: string | null;
  message: string;
}

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
  if (typeof reference !== "string" || !reference.startsWith("#/")) {
    return schema;
  }
  const target = reference
    .slice(2)
    .split("/")
    .map((segment) => segment.replaceAll("~1", "/").replaceAll("~0", "~"))
    .reduce<unknown>((current, segment) => record(current)?.[segment], root);
  return record(target) ?? schema;
}

function schemaMatchesType(type: unknown, value: unknown): boolean {
  if (Array.isArray(type)) {
    return type.some((candidate) => schemaMatchesType(candidate, value));
  }
  switch (type) {
    case "null":
      return value === null;
    case "object":
      return record(value) !== null;
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "boolean":
      return typeof value === "boolean";
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    default:
      return true;
  }
}

function sameJsonValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (typeof left !== "object" || left === null) return false;
  if (typeof right !== "object" || right === null) return false;
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
}

function configValueIssues(
  schema: Record<string, unknown>,
  value: unknown,
  root: Record<string, unknown>,
  fieldName: string | null,
  depth = 0,
): ConfigValidationIssue[] {
  if (depth > 64)
    return [{ fieldName, message: "Schema nesting is too deep." }];

  const issues: ConfigValidationIssue[] = [];
  const reference = resolveSchema(schema, root);
  if (reference !== schema) {
    issues.push(
      ...configValueIssues(reference, value, root, fieldName, depth + 1),
    );
  }

  if (!schemaMatchesType(schema.type, value)) {
    return [
      ...issues,
      { fieldName, message: `Expected ${String(schema.type)}.` },
    ];
  }

  for (const keyword of ["allOf", "anyOf", "oneOf"] as const) {
    const branches = schema[keyword];
    if (!Array.isArray(branches)) continue;
    const branchIssues = branches.map((branch) => {
      const branchSchema = record(branch);
      return branchSchema
        ? configValueIssues(branchSchema, value, root, fieldName, depth + 1)
        : [{ fieldName, message: "Invalid schema branch." }];
    });
    const matchingBranches = branchIssues.filter((branch) => !branch.length);
    if (keyword === "allOf") {
      for (const branch of branchIssues) issues.push(...branch);
    } else if (
      (keyword === "anyOf" && matchingBranches.length === 0) ||
      (keyword === "oneOf" && matchingBranches.length !== 1)
    ) {
      const bestBranch = branchIssues.reduce<ConfigValidationIssue[]>(
        (best, current) => (current.length < best.length ? current : best),
        branchIssues[0] ?? [],
      );
      issues.push(
        ...(bestBranch.length
          ? bestBranch
          : [{ fieldName, message: "Value must match exactly one schema." }]),
      );
    }
  }

  if (
    Array.isArray(schema.enum) &&
    !schema.enum.some((candidate) => sameJsonValue(candidate, value))
  ) {
    issues.push({ fieldName, message: "Choose one of the allowed values." });
  }

  if (typeof value === "number") {
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      issues.push({
        fieldName,
        message: `Must be at least ${schema.minimum}.`,
      });
    }
    if (typeof schema.maximum === "number" && value > schema.maximum) {
      issues.push({ fieldName, message: `Must be at most ${schema.maximum}.` });
    }
    if (
      typeof schema.exclusiveMinimum === "number" &&
      value <= schema.exclusiveMinimum
    ) {
      issues.push({
        fieldName,
        message: `Must be greater than ${schema.exclusiveMinimum}.`,
      });
    }
    if (
      typeof schema.exclusiveMaximum === "number" &&
      value >= schema.exclusiveMaximum
    ) {
      issues.push({
        fieldName,
        message: `Must be less than ${schema.exclusiveMaximum}.`,
      });
    }
  }

  if (typeof value === "string") {
    const length = Array.from(value).length;
    if (typeof schema.minLength === "number" && length < schema.minLength) {
      issues.push({
        fieldName,
        message: `Use at least ${schema.minLength} characters.`,
      });
    }
    if (typeof schema.maxLength === "number" && length > schema.maxLength) {
      issues.push({
        fieldName,
        message: `Use at most ${schema.maxLength} characters.`,
      });
    }
    if (typeof schema.pattern === "string") {
      try {
        if (!new RegExp(schema.pattern).test(value)) {
          issues.push({
            fieldName,
            message: "Value does not match the required format.",
          });
        }
      } catch {
        issues.push({
          fieldName,
          message: "The schema contains an invalid pattern.",
        });
      }
    }
  }

  const objectValue = record(value);
  if (objectValue) {
    const properties = record(schema.properties);
    const required = Array.isArray(schema.required)
      ? schema.required.filter(
          (name): name is string => typeof name === "string",
        )
      : [];
    for (const name of required) {
      if (!Object.hasOwn(objectValue, name)) {
        issues.push({ fieldName: name, message: "This field is required." });
      }
    }
    for (const [name, propertySchema] of Object.entries(properties ?? {})) {
      if (!Object.hasOwn(objectValue, name)) continue;
      const childSchema = record(propertySchema);
      if (!childSchema) continue;
      issues.push(
        ...configValueIssues(
          childSchema,
          objectValue[name],
          root,
          fieldName ?? name,
          depth + 1,
        ),
      );
    }
    for (const [name, childValue] of Object.entries(objectValue)) {
      if (properties && Object.hasOwn(properties, name)) continue;
      if (schema.additionalProperties === false) {
        issues.push({ fieldName: name, message: "This key is not allowed." });
      } else {
        const extraSchema = record(schema.additionalProperties);
        if (extraSchema) {
          issues.push(
            ...configValueIssues(
              extraSchema,
              childValue,
              root,
              fieldName ?? name,
              depth + 1,
            ),
          );
        }
      }
    }
  }

  if (Array.isArray(value)) {
    const prefixItems = Array.isArray(schema.prefixItems)
      ? schema.prefixItems
      : [];
    if (typeof schema.minItems === "number" && value.length < schema.minItems) {
      issues.push({
        fieldName,
        message: `Provide at least ${schema.minItems} items.`,
      });
    }
    if (typeof schema.maxItems === "number" && value.length > schema.maxItems) {
      issues.push({
        fieldName,
        message: `Provide at most ${schema.maxItems} items.`,
      });
    }
    value.forEach((item, index) => {
      const itemSchema = record(prefixItems[index] ?? schema.items);
      if (itemSchema) {
        issues.push(
          ...configValueIssues(itemSchema, item, root, fieldName, depth + 1),
        );
      }
    });
  }

  return issues;
}

/** Validate persisted config values against the emitted JSON Schema locally. */
export function validateConfig(
  rawSchema: unknown,
  config: unknown,
): ConfigValidationIssue[] {
  const schema = record(rawSchema);
  if (!schema) return [];
  return configValueIssues(schema, config, schema, null);
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
