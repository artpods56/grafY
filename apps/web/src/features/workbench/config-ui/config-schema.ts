import { createUuid } from "../authoring/uuid";

export type ConfigWidgetKind =
  | "textarea"
  | "slider"
  | "color"
  | "segmented"
  | "switch"
  | "one-based-integer";

export type VisibleWhenPredicate =
  | { readonly field: string; readonly eq: unknown }
  | { readonly field: string; readonly neq: unknown }
  | { readonly field: string; readonly in: readonly unknown[] }
  | { readonly field: string; readonly truthy: boolean }
  | { readonly portConnected: string; readonly is?: boolean }
  | {
      readonly portArtifactType: {
        readonly port: string;
        readonly in?: readonly string[];
        readonly notIn?: readonly string[];
        readonly whenUnconnected?: "show" | "hide";
      };
    }
  | { readonly all: readonly VisibleWhenPredicate[] }
  | { readonly any: readonly VisibleWhenPredicate[] }
  | { readonly not: VisibleWhenPredicate };

interface SchemaFieldBase {
  name: string;
  title: string;
  description?: string;
  enumValues?: readonly (string | number)[];
  format?: "textarea";
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  required: boolean;
  nullable: boolean;
  advanced?: boolean;
  defaultValue?: unknown;
  widget?: ConfigWidgetKind;
  enumLabels?: Readonly<Record<string, string>>;
  group?: string;
  visibleWhen?: VisibleWhenPredicate;
  autoId?: boolean;
  examples?: readonly unknown[];
}

type PrimitiveType = "string" | "integer" | "number" | "boolean";

export interface ScalarSchemaField extends SchemaFieldBase {
  type: PrimitiveType;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
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

export interface PrimitiveListSchemaField extends SchemaFieldBase {
  type: "primitive-list";
  allowedTypes: readonly PrimitiveType[];
  minItems?: number;
  maxItems?: number;
}

export interface ObjectSchemaField extends SchemaFieldBase {
  type: "object";
  fields: readonly SchemaField[];
  autoIdFields?: readonly string[];
  constFields?: Readonly<Record<string, unknown>>;
}

export interface DiscriminatedUnionBranch {
  tag: string;
  label: string;
  fields: readonly SchemaField[];
  constFields: Readonly<Record<string, unknown>>;
  autoIdFields?: readonly string[];
}

export interface DiscriminatedUnionSchemaField extends SchemaFieldBase {
  type: "discriminated-union";
  discriminator: string;
  branches: readonly DiscriminatedUnionBranch[];
}

export interface ObjectListSchemaField extends SchemaFieldBase {
  type: "object-list";
  itemTitle: string;
  itemFields: readonly SchemaField[];
  itemAutoIdFields?: readonly string[];
  itemConstFields?: Readonly<Record<string, unknown>>;
  minItems?: number;
  maxItems?: number;
}

export type SchemaField =
  | ScalarSchemaField
  | NumberTupleSchemaField
  | StringListSchemaField
  | PrimitiveListSchemaField
  | ObjectSchemaField
  | DiscriminatedUnionSchemaField
  | ObjectListSchemaField;

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
  const visited = new Set<string>();
  const siblings: Record<string, unknown>[] = [];
  let current = schema;
  while (typeof current.$ref === "string" && current.$ref.startsWith("#/")) {
    const { $ref, ...local } = current;
    if (visited.has($ref)) break;
    visited.add($ref);
    const target = $ref
      .slice(2)
      .split("/")
      .map((segment) => segment.replaceAll("~1", "/").replaceAll("~0", "~"))
      .reduce<unknown>((value, segment) => {
        const object = record(value);
        return object && Object.hasOwn(object, segment)
          ? object[segment]
          : undefined;
      }, root);
    const targetSchema = record(target);
    if (!targetSchema) break;
    siblings.push(local);
    current = targetSchema;
  }
  if (!siblings.length) return current;
  const { $ref: _reference, ...target } = current;
  return siblings.reduceRight(
    (merged, local) => ({ ...merged, ...local }),
    target,
  );
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
  if (left === right) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((item, index) => sameJsonValue(item, right[index]))
    );
  }
  const leftObject = record(left);
  const rightObject = record(right);
  if (!leftObject || !rightObject) return false;
  const entries = Object.entries(leftObject);
  return (
    entries.length === Object.keys(rightObject).length &&
    entries.every(
      ([key, value]) =>
        Object.hasOwn(rightObject, key) &&
        sameJsonValue(value, rightObject[key]),
    )
  );
}

function configValueIssues(
  rawSchema: Record<string, unknown>,
  value: unknown,
  root: Record<string, unknown>,
  fieldName: string | null,
  depth = 0,
): ConfigValidationIssue[] {
  if (depth > 64)
    return [{ fieldName, message: "Schema nesting is too deep." }];

  const issues: ConfigValidationIssue[] = [];
  const schema = resolveSchema(rawSchema, root);

  if (!schemaMatchesType(schema.type, value)) {
    return [{ fieldName, message: `Expected ${String(schema.type)}.` }];
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

  if (Object.hasOwn(schema, "const") && !sameJsonValue(schema.const, value)) {
    issues.push({ fieldName, message: "Use the required literal value." });
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
        // A nested key is reported against the top-level field that owns it.
        issues.push({
          fieldName: fieldName ?? name,
          message: "This field is required.",
        });
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
        issues.push({
          fieldName: fieldName ?? name,
          message: "This key is not allowed.",
        });
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
    .filter((branch): branch is Record<string, unknown> => branch !== null)
    .map((branch) => resolveSchema(branch, root));
  const nullBranches = branches.filter((branch) => branch.type === "null");
  const valueBranches = branches.filter((branch) => branch.type !== "null");
  if (
    branches.length !== 2 ||
    nullBranches.length !== 1 ||
    valueBranches.length !== 1
  ) {
    return { schema: resolved, nullable: false };
  }
  const [valueBranch] = valueBranches;
  if (!valueBranch) return { schema: resolved, nullable: false };
  return {
    schema: valueBranch,
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
  items: Record<string, unknown>,
): Omit<
  StringListSchemaField,
  keyof SchemaFieldBase | "type" | "minItems" | "maxItems"
> {
  return {
    itemMinLength:
      typeof items.minLength === "number" ? items.minLength : undefined,
    itemMaxLength:
      typeof items.maxLength === "number" ? items.maxLength : undefined,
    itemPattern: typeof items.pattern === "string" ? items.pattern : undefined,
  };
}

const MAX_FIELD_DEPTH = 8;

function isPrimitiveType(type: unknown): type is PrimitiveType {
  return (
    type === "string" ||
    type === "integer" ||
    type === "number" ||
    type === "boolean"
  );
}

function isWidgetKind(value: unknown): value is ConfigWidgetKind {
  return (
    value === "textarea" ||
    value === "slider" ||
    value === "color" ||
    value === "segmented" ||
    value === "switch" ||
    value === "one-based-integer"
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isStringArray(value: unknown): value is readonly string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function isStringMap(
  value: unknown,
): value is Readonly<Record<string, string>> {
  const object = record(value);
  if (!object) return false;
  const prototype = Object.getPrototypeOf(object);
  return (
    (prototype === Object.prototype || prototype === null) &&
    Object.values(object).every((item) => typeof item === "string")
  );
}

function isJsonValue(value: unknown, depth = 0): boolean {
  if (depth > 64) return false;
  if (value === null || typeof value === "string" || typeof value === "boolean")
    return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value))
    return value.every((item) => isJsonValue(item, depth + 1));
  const object = record(value);
  if (!object) return false;
  const prototype = Object.getPrototypeOf(object);
  return (
    (prototype === Object.prototype || prototype === null) &&
    Object.values(object).every((item) => isJsonValue(item, depth + 1))
  );
}

function parseVisibleWhen(
  value: unknown,
  depth = 0,
): VisibleWhenPredicate | undefined {
  const condition = record(value);
  if (!condition || depth > MAX_FIELD_DEPTH) return undefined;
  const keys = Object.keys(condition);
  const { field, portConnected, is } = condition;
  if (keys.length === 2 && isNonEmptyString(field)) {
    if (isJsonValue(condition.eq)) return { field, eq: condition.eq };
    if (isJsonValue(condition.neq)) return { field, neq: condition.neq };
    if (
      Array.isArray(condition.in) &&
      condition.in.every((item) => isJsonValue(item))
    ) {
      return { field, in: condition.in };
    }
    if (typeof condition.truthy === "boolean")
      return { field, truthy: condition.truthy };
  }
  if (
    keys.every((key) => key === "portConnected" || key === "is") &&
    isNonEmptyString(portConnected) &&
    (is === undefined || typeof is === "boolean")
  ) {
    return is === undefined ? { portConnected } : { portConnected, is };
  }
  if (keys.length !== 1) return undefined;
  const artifact = record(condition.portArtifactType);
  if (artifact) {
    const { port, in: included, notIn, whenUnconnected } = artifact;
    if (
      !isNonEmptyString(port) ||
      Object.keys(artifact).some(
        (key) => !["port", "in", "notIn", "whenUnconnected"].includes(key),
      ) ||
      (included !== undefined && !isStringArray(included)) ||
      (notIn !== undefined && !isStringArray(notIn)) ||
      (whenUnconnected !== undefined &&
        whenUnconnected !== "show" &&
        whenUnconnected !== "hide")
    )
      return undefined;
    return {
      portArtifactType: {
        port,
        ...(included !== undefined ? { in: included } : {}),
        ...(notIn !== undefined ? { notIn } : {}),
        ...(whenUnconnected !== undefined ? { whenUnconnected } : {}),
      },
    };
  }
  for (const operator of ["all", "any"] as const) {
    const children = condition[operator];
    if (!Array.isArray(children)) continue;
    const predicates: VisibleWhenPredicate[] = [];
    for (const child of children) {
      const predicate = parseVisibleWhen(child, depth + 1);
      if (!predicate) return undefined;
      predicates.push(predicate);
    }
    return operator === "all" ? { all: predicates } : { any: predicates };
  }
  if (Object.hasOwn(condition, "not")) {
    const predicate = parseVisibleWhen(condition.not, depth + 1);
    if (predicate) return { not: predicate };
  }
  return undefined;
}

function fieldMetadata(
  name: string,
  schema: Record<string, unknown>,
  required: boolean,
  nullable: boolean,
): SchemaFieldBase {
  const widget = schema["x-grafy-widget"];
  const labels = schema["x-grafy-enum-labels"];
  const group = schema["x-grafy-group"];
  const visibleWhen = parseVisibleWhen(schema["x-grafy-visible-when"]);

  return {
    name,
    title:
      typeof schema.title === "string"
        ? schema.title
        : name.replaceAll("_", " "),
    description:
      typeof schema.description === "string" ? schema.description : undefined,
    required,
    nullable,
    ...(schema["x-grafy-advanced"] === true ? { advanced: true } : {}),
    ...(Object.hasOwn(schema, "default")
      ? { defaultValue: schema.default }
      : {}),
    ...(isWidgetKind(widget) ? { widget } : {}),
    ...(isStringMap(labels) ? { enumLabels: labels } : {}),
    ...(isNonEmptyString(group) ? { group } : {}),
    ...(visibleWhen ? { visibleWhen } : {}),
    ...(schema["x-grafy-auto-id"] === true ? { autoId: true } : {}),
    ...(Array.isArray(schema.examples) ? { examples: schema.examples } : {}),
  };
}

type ObjectFields = Pick<
  ObjectSchemaField,
  "fields" | "constFields" | "autoIdFields"
>;

function objectFields(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
  depth: number,
): ObjectFields {
  const required = new Set(
    Array.isArray(schema.required) ? schema.required : [],
  );
  const fields: SchemaField[] = [];
  const autoIdFields: string[] = [];
  const constants: [string, unknown][] = [];
  if (depth > MAX_FIELD_DEPTH) return { fields };
  for (const [name, rawProperty] of Object.entries(
    record(schema.properties) ?? {},
  )) {
    const raw = record(rawProperty);
    if (!raw) continue;
    const metadata = resolveSchema(raw, root);
    const { schema: property, nullable } = editableSchema(metadata, root);
    if (depth > 0) {
      if (Object.hasOwn(property, "const")) {
        constants.push([name, property.const]);
        continue;
      }
      if (
        metadata["x-grafy-auto-id"] === true ||
        property["x-grafy-auto-id"] === true
      ) {
        autoIdFields.push(name);
        continue;
      }
    }
    if (
      metadata["x-grafy-hidden"] === true ||
      property["x-grafy-hidden"] === true
    )
      continue;

    const common = fieldMetadata(
      name,
      { ...property, ...metadata },
      required.has(name),
      nullable,
    );
    if (
      metadata["x-grafy-advanced"] === true ||
      property["x-grafy-advanced"] === true
    ) {
      common.advanced = true;
    }
    const field = parseField(property, common, root, depth);
    if (field) fields.push(field);
  }
  return {
    fields,
    ...(autoIdFields.length ? { autoIdFields } : {}),
    ...(constants.length ? { constFields: Object.fromEntries(constants) } : {}),
  };
}

function discriminatedUnion(
  schema: Record<string, unknown>,
  common: SchemaFieldBase,
  root: Record<string, unknown>,
  depth: number,
): DiscriminatedUnionSchemaField | undefined {
  const rawBranches = schema.oneOf ?? schema.anyOf;
  if (!Array.isArray(rawBranches) || rawBranches.length < 2) return undefined;

  const discriminatorMetadata = record(schema.discriminator);
  const mapping = record(discriminatorMetadata?.mapping);
  const branches: (ObjectFields & {
    schema: Record<string, unknown>;
    reference: unknown;
  })[] = [];
  for (const rawBranch of rawBranches) {
    const raw = record(rawBranch);
    if (!raw) return undefined;
    const branch = resolveSchema(raw, root);
    if (branch.type !== "object" || !record(branch.properties))
      return undefined;
    branches.push({
      schema: branch,
      reference: raw.$ref,
      ...objectFields(branch, root, depth + 1),
    });
  }

  const first = branches[0];
  const declared = discriminatorMetadata?.propertyName;
  const discriminator = isNonEmptyString(declared)
    ? declared
    : Object.keys(first?.constFields ?? {}).find((key) => {
        const tags = branches.map((branch) => branch.constFields?.[key]);
        return (
          tags.every((tag) => typeof tag === "string") &&
          new Set(tags).size === branches.length
        );
      });
  if (!discriminator) return undefined;

  const variants: DiscriminatedUnionBranch[] = [];
  const usedTags = new Set<string>();
  for (const branch of branches) {
    const literal = branch.constFields?.[discriminator];
    const tag =
      typeof literal === "string"
        ? literal
        : branch.reference === undefined
          ? undefined
          : Object.keys(mapping ?? {}).find(
              (key) => mapping?.[key] === branch.reference,
            );
    if (tag === undefined || usedTags.has(tag)) return undefined;
    usedTags.add(tag);
    const branchTitle =
      typeof branch.schema.title === "string" ? branch.schema.title : tag;
    variants.push({
      tag,
      label:
        common.enumLabels && Object.hasOwn(common.enumLabels, tag)
          ? (common.enumLabels[tag] ?? branchTitle)
          : branchTitle,
      fields: branch.fields.filter((field) => field.name !== discriminator),
      constFields: { ...branch.constFields, [discriminator]: tag },
      ...(branch.autoIdFields ? { autoIdFields: branch.autoIdFields } : {}),
    });
  }
  return {
    ...common,
    type: "discriminated-union",
    discriminator,
    branches: variants,
  };
}

function arrayField(
  schema: Record<string, unknown>,
  common: SchemaFieldBase,
  root: Record<string, unknown>,
  depth: number,
): SchemaField | undefined {
  const tupleItems = fixedNumberTupleItems(schema, root);
  if (tupleItems) return { ...common, type: "number-tuple", items: tupleItems };

  const rawItems = record(schema.items);
  if (!rawItems) return undefined;
  const items = resolveSchema(rawItems, root);
  const bounds = {
    minItems: typeof schema.minItems === "number" ? schema.minItems : undefined,
    maxItems: typeof schema.maxItems === "number" ? schema.maxItems : undefined,
  };
  if (items.type === "string") {
    return {
      ...common,
      ...bounds,
      type: "string-list",
      ...stringListConstraints(items),
    };
  }
  if (
    items.type === "object" &&
    record(items.properties) &&
    depth < MAX_FIELD_DEPTH
  ) {
    const object = objectFields(items, root, depth + 1);
    return {
      ...common,
      ...bounds,
      type: "object-list",
      itemTitle: typeof items.title === "string" ? items.title : "Item",
      itemFields: object.fields,
      ...(object.autoIdFields ? { itemAutoIdFields: object.autoIdFields } : {}),
      ...(object.constFields ? { itemConstFields: object.constFields } : {}),
    };
  }
  if (Array.isArray(items.anyOf) && items.anyOf.length) {
    const types = items.anyOf.map((branch) => {
      const raw = record(branch);
      return raw ? resolveSchema(raw, root).type : undefined;
    });
    if (types.every(isPrimitiveType)) {
      return {
        ...common,
        ...bounds,
        type: "primitive-list",
        allowedTypes: [...new Set(types)],
      };
    }
  }
  return undefined;
}

function parseField(
  schema: Record<string, unknown>,
  common: SchemaFieldBase,
  root: Record<string, unknown>,
  depth: number,
): SchemaField | undefined {
  if (schema.type === "array") return arrayField(schema, common, root, depth);
  if (depth < MAX_FIELD_DEPTH) {
    const union = discriminatedUnion(schema, common, root, depth);
    if (union) return union;
    if (schema.type === "object" && record(schema.properties)) {
      return {
        ...common,
        type: "object",
        ...objectFields(schema, root, depth + 1),
      };
    }
  }

  const enumValues = Array.isArray(schema.enum)
    ? schema.enum.filter(
        (value): value is string | number =>
          typeof value === "string" || typeof value === "number",
      )
    : undefined;
  const type =
    typeof schema.type === "string"
      ? schema.type
      : enumValues?.every((value) => typeof value === "number")
        ? "number"
        : enumValues?.length
          ? "string"
          : null;
  if (!isPrimitiveType(type)) return undefined;

  return {
    ...common,
    type,
    enumValues,
    format: schema.format === "textarea" ? "textarea" : undefined,
    minimum: typeof schema.minimum === "number" ? schema.minimum : undefined,
    maximum: typeof schema.maximum === "number" ? schema.maximum : undefined,
    minLength:
      typeof schema.minLength === "number" ? schema.minLength : undefined,
    maxLength:
      typeof schema.maxLength === "number" ? schema.maxLength : undefined,
    pattern: typeof schema.pattern === "string" ? schema.pattern : undefined,
    ...(typeof schema.exclusiveMinimum === "number"
      ? { exclusiveMinimum: schema.exclusiveMinimum }
      : {}),
    ...(typeof schema.exclusiveMaximum === "number"
      ? { exclusiveMaximum: schema.exclusiveMaximum }
      : {}),
  };
}

/** A generated model name ("GeoFillStyle") is a class, not a label. */
const MODEL_CLASS_NAME = /^(?:[A-Z][a-z0-9]+){2,}$/;

/**
 * The name a person reads for a field. Pydantic titles a `$ref`'d model field
 * with the model's class name; the property name ("fill") is what it is.
 */
export function fieldDisplayTitle(
  field: Pick<SchemaFieldBase, "name" | "title">,
): string {
  return MODEL_CLASS_NAME.test(field.title)
    ? field.name.replaceAll("_", " ")
    : field.title;
}

/** Parse the supported editable field shapes from an operator config schema. */
export function schemaFields(rawSchema: unknown): SchemaField[] {
  const root = record(rawSchema);
  return root
    ? [...objectFields(resolveSchema(root, root), root, 0).fields]
    : [];
}

export interface ConnectedInputPortInfo {
  readonly connected: boolean;
  readonly artifactTypeKey: string | null;
}

export type ConnectedInputPortMap = Readonly<
  Record<string, ConnectedInputPortInfo>
>;

export interface ConfigVisibilityContext {
  readonly config: Readonly<Record<string, unknown>>;
  readonly connectedPorts?: ConnectedInputPortMap;
}

export function evaluateVisibleWhen(
  predicate: VisibleWhenPredicate,
  context: ConfigVisibilityContext,
  defaults?: Readonly<Record<string, unknown>>,
): boolean {
  if ("field" in predicate) {
    const value =
      context.config[predicate.field] === undefined
        ? defaults?.[predicate.field]
        : context.config[predicate.field];
    if ("eq" in predicate) return sameJsonValue(value, predicate.eq);
    if ("neq" in predicate) return !sameJsonValue(value, predicate.neq);
    if ("in" in predicate)
      return predicate.in.some((item) => sameJsonValue(value, item));
    const truthy =
      value !== undefined &&
      value !== null &&
      value !== false &&
      value !== 0 &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0);
    return truthy === predicate.truthy;
  }
  if ("portConnected" in predicate) {
    return (
      Boolean(context.connectedPorts?.[predicate.portConnected]?.connected) ===
      (predicate.is ?? true)
    );
  }
  if ("portArtifactType" in predicate) {
    const condition = predicate.portArtifactType;
    const input = context.connectedPorts?.[condition.port];
    if (!input?.connected || input.artifactTypeKey === null) {
      return (
        (condition.whenUnconnected ?? (condition.in ? "hide" : "show")) ===
        "show"
      );
    }
    return (
      (!condition.in || condition.in.includes(input.artifactTypeKey)) &&
      !condition.notIn?.includes(input.artifactTypeKey)
    );
  }
  if ("all" in predicate) {
    return predicate.all.every((child) =>
      evaluateVisibleWhen(child, context, defaults),
    );
  }
  if ("any" in predicate) {
    return predicate.any.some((child) =>
      evaluateVisibleWhen(child, context, defaults),
    );
  }
  return !evaluateVisibleWhen(predicate.not, context, defaults);
}

export function visibleSchemaFields(
  fields: readonly SchemaField[],
  context: ConfigVisibilityContext,
  issues?: readonly ConfigValidationIssue[],
): SchemaField[] {
  const defaults = Object.fromEntries(
    fields.map((field) => [field.name, field.defaultValue]),
  );
  const invalidFields = new Set(issues?.map((issue) => issue.fieldName));
  return fields.filter(
    (field) =>
      !field.visibleWhen ||
      invalidFields.has(field.name) ||
      evaluateVisibleWhen(field.visibleWhen, context, defaults),
  );
}

interface DefaultOptions {
  index?: number;
  generateId?: () => string;
}

function numericDefault(field: NumberTupleItem | ScalarSchemaField): number {
  const exclusiveMinimum =
    "exclusiveMinimum" in field ? field.exclusiveMinimum : undefined;
  const exclusiveMaximum =
    "exclusiveMaximum" in field ? field.exclusiveMaximum : undefined;
  let minimum = field.minimum ?? -Infinity;
  let maximum = field.maximum ?? Infinity;
  if (field.type === "integer") {
    if (exclusiveMinimum !== undefined)
      minimum = Math.max(minimum, Math.floor(exclusiveMinimum) + 1);
    if (exclusiveMaximum !== undefined)
      maximum = Math.min(maximum, Math.ceil(exclusiveMaximum) - 1);
    return Math.min(Math.floor(maximum), Math.max(Math.ceil(minimum), 0));
  }

  minimum = Math.max(minimum, exclusiveMinimum ?? -Infinity);
  maximum = Math.min(maximum, exclusiveMaximum ?? Infinity);
  const candidate = Math.min(maximum, Math.max(minimum, 0));
  const withinExclusiveBounds = (value: number) =>
    (exclusiveMinimum === undefined || value > exclusiveMinimum) &&
    (exclusiveMaximum === undefined || value < exclusiveMaximum);
  if (withinExclusiveBounds(candidate)) return candidate;
  if (Number.isFinite(minimum) && Number.isFinite(maximum)) {
    const midpoint = minimum / 2 + maximum / 2;
    if (withinExclusiveBounds(midpoint)) return midpoint;
    return withinExclusiveBounds(minimum) ? minimum : maximum;
  }
  if (Number.isFinite(minimum)) {
    return minimum + Math.max(1, Math.abs(minimum) * Number.EPSILON);
  }
  return maximum - Math.max(1, Math.abs(maximum) * Number.EPSILON);
}

function objectDefault(
  shape: ObjectFields,
  options: DefaultOptions,
): Record<string, unknown> {
  const { index = 0, generateId = createUuid } = options;
  return {
    ...Object.fromEntries(
      shape.fields.map((field) => [
        field.name,
        buildDefaultForField(field, options),
      ]),
    ),
    ...structuredClone(shape.constFields ?? {}),
    ...Object.fromEntries(
      (shape.autoIdFields ?? []).map((name) => [
        name,
        `item_${index + 1}_${generateId().slice(0, 8)}`,
      ]),
    ),
  };
}

export function buildDefaultForField(
  field: SchemaField,
  options: DefaultOptions = {},
): unknown {
  if (field.defaultValue !== undefined)
    return structuredClone(field.defaultValue);
  if (field.examples?.[0] !== undefined)
    return structuredClone(field.examples[0]);

  switch (field.type) {
    case "object":
      return objectDefault(field, options);
    case "discriminated-union": {
      const branch = field.branches[0];
      return branch ? objectDefault(branch, options) : {};
    }
    case "object-list":
      return Array.from({ length: field.minItems ?? 0 }, (_, index) =>
        objectDefault(
          {
            fields: field.itemFields,
            constFields: field.itemConstFields,
            autoIdFields: field.itemAutoIdFields,
          },
          { ...options, index },
        ),
      );
    case "string-list":
      return Array.from({ length: field.minItems ?? 0 }, () =>
        "a".repeat(field.itemMinLength ?? 0),
      );
    case "primitive-list":
      return Array.from({ length: field.minItems ?? 0 }, () => {
        const type = field.allowedTypes[0];
        return type === "string" ? "" : type === "boolean" ? false : 0;
      });
    case "number-tuple":
      return field.items.map(numericDefault);
    case "string":
      return (
        field.enumValues?.[0] ??
        (field.widget === "color"
          ? "#000000"
          : "a".repeat(field.minLength ?? 0))
      );
    case "number":
    case "integer":
      return field.enumValues?.[0] ?? numericDefault(field);
    case "boolean":
      return false;
  }
}
