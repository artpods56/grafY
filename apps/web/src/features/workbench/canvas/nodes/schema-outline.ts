type Schema = Record<string, unknown>;

export type OutlineKind = "field" | "branch" | "items";

export interface OutlineNode {
  id: string;
  name: string;
  typeLabel: string;
  required: boolean;
  kind: OutlineKind;
  children: OutlineNode[];
  expandable: boolean;
}

function record(value: unknown): Schema | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Schema;
}

function dereference(schema: Schema, root: Schema): Schema {
  let current = schema;
  const visited = new Set<string>();
  while (typeof current.$ref === "string" && !visited.has(current.$ref)) {
    const reference = current.$ref;
    visited.add(reference);
    if (!reference.startsWith("#/$defs/")) break;
    const definitions = record(root.$defs);
    const resolved = record(definitions?.[reference.slice("#/$defs/".length)]);
    if (!resolved) break;
    current = resolved;
  }
  return current;
}

function unionMembers(
  schema: Schema,
  root: Schema,
): {
  members: Schema[];
  optional: boolean;
} {
  const resolved = dereference(schema, root);
  const raw = resolved.oneOf ?? resolved.anyOf;
  if (!Array.isArray(raw)) {
    return { members: [resolved], optional: false };
  }
  const members = raw.flatMap((candidate) => {
    const candidateSchema = record(candidate);
    return candidateSchema ? [dereference(candidateSchema, root)] : [];
  });
  const optional = members.some((member) => member.type === "null");
  const concrete = members.filter((member) => member.type !== "null");
  return {
    members: concrete.length ? concrete : members,
    optional,
  };
}

function branchName(schema: Schema): string {
  const properties = record(schema.properties);
  const kind = record(properties?.kind);
  if (typeof kind?.const === "string") return kind.const;
  if (typeof schema.title === "string") return schema.title;
  return "variant";
}

function scalarLabel(schema: Schema): string {
  if (Array.isArray(schema.enum)) {
    return schema.enum.map(String).join(" | ");
  }
  if (typeof schema.const === "string") return `"${schema.const}"`;
  switch (schema.type) {
    case "string":
      return "str";
    case "integer":
      return "int";
    case "number":
      return "float";
    case "boolean":
      return "bool";
    case "null":
      return "None";
    case "array":
      return "list";
    case "object":
      return typeof schema.title === "string" ? schema.title : "object";
    default:
      return record(schema.properties) ? "object" : "any";
  }
}

/** Python-flavored type label for a JSON-schema fragment. */
export function schemaTypeLabel(
  schema: Schema | null | undefined,
  root: Schema | null | undefined = schema,
): string {
  if (!schema || !root) return "any";
  const { members, optional } = unionMembers(schema, root);
  if (members.length > 1) {
    const labels = members.map((member) => {
      const kind = branchName(member);
      return kind === "variant" ? scalarLabel(member) : kind;
    });
    const joined = [...new Set(labels)].join(" | ");
    return optional && !joined.includes("None") ? `${joined} | None` : joined;
  }
  const resolved = members[0];
  if (!resolved) return optional ? "None" : "any";
  if (resolved.type === "array") {
    if (Array.isArray(resolved.prefixItems)) {
      return `tuple[${resolved.prefixItems.length}]`;
    }
    return `list[${schemaTypeLabel(record(resolved.items) ?? {}, root)}]`;
  }
  const label = scalarLabel(resolved);
  return optional && label !== "None" ? `${label} | None` : label;
}

function isExpandable(schema: Schema, root: Schema): boolean {
  const { members } = unionMembers(schema, root);
  if (members.length > 1) return true;
  const resolved = members[0];
  if (!resolved) return false;
  if (record(resolved.properties)) return true;
  if (resolved.type === "array") return true;
  return false;
}

function childrenOf(
  schema: Schema,
  root: Schema,
  idPrefix: string,
  depth: number,
): OutlineNode[] {
  if (depth > 10) return [];
  const { members } = unionMembers(schema, root);
  if (members.length > 1) {
    return members.map((member) => {
      const name = branchName(member);
      const id = `${idPrefix}/as:${name}`;
      const children = childrenOf(member, root, id, depth + 1);
      return {
        id,
        name: `as ${name}`,
        typeLabel: schemaTypeLabel(member, root),
        required: false,
        kind: "branch" as const,
        expandable: children.length > 0,
        children,
      };
    });
  }

  const resolved = members[0];
  if (!resolved) return [];

  if (resolved.type === "array") {
    if (Array.isArray(resolved.prefixItems)) {
      return resolved.prefixItems.flatMap((item, index) => {
        const itemSchema = record(item);
        if (!itemSchema) return [];
        const id = `${idPrefix}/[${index}]`;
        const children = childrenOf(itemSchema, root, id, depth + 1);
        return [
          {
            id,
            name:
              typeof itemSchema.title === "string"
                ? itemSchema.title
                : `[${index}]`,
            typeLabel: schemaTypeLabel(itemSchema, root),
            required: true,
            kind: "items" as const,
            expandable: children.length > 0,
            children,
          },
        ];
      });
    }
    const items = record(resolved.items);
    if (!items) return [];
    const id = `${idPrefix}/[]`;
    const children = childrenOf(items, root, id, depth + 1);
    return [
      {
        id,
        name: "item",
        typeLabel: schemaTypeLabel(items, root),
        required: false,
        kind: "items",
        expandable: children.length > 0,
        children,
      },
    ];
  }

  const properties = record(resolved.properties);
  if (!properties) return [];
  const required = new Set(
    Array.isArray(resolved.required)
      ? resolved.required.filter(
          (value): value is string => typeof value === "string",
        )
      : [],
  );

  return Object.entries(properties).map(([name, raw]) => {
    const property = record(raw) ?? {};
    const id = `${idPrefix}/${name}`;
    const children = childrenOf(property, root, id, depth + 1);
    return {
      id,
      name,
      typeLabel: schemaTypeLabel(property, root),
      required: required.has(name),
      kind: "field" as const,
      expandable: children.length > 0 || isExpandable(property, root),
      children,
    };
  });
}

export function schemaOutline(schema: Schema): OutlineNode[] {
  return childrenOf(schema, schema, "root", 0);
}

export function findOutlineNode(
  nodes: readonly OutlineNode[],
  id: string,
): OutlineNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const nested = findOutlineNode(node.children, id);
    if (nested) return nested;
  }
  return undefined;
}

export function outlineCrumbLabel(node: OutlineNode): string {
  return node.kind === "branch" && node.name.startsWith("as ")
    ? node.name.slice(3)
    : node.name;
}

export function schemaTitle(schema: Schema, fallback = "Payload"): string {
  return typeof schema.title === "string" && schema.title
    ? schema.title
    : fallback;
}
