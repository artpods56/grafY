export function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function formatJsonSchemaPayload(payload: unknown): string | null {
  const schemaText = record(payload)?.value;
  if (typeof schemaText !== "string") return null;

  try {
    const schema: unknown = JSON.parse(schemaText);
    if (record(schema) === null) return null;
    return JSON.stringify(schema, null, 2);
  } catch {
    return null;
  }
}

export interface MarkdownArtifactPayload {
  markdown: string;
}

export function markdownPayload(
  payload: unknown,
): MarkdownArtifactPayload | null {
  const markdown = record(payload)?.markdown;
  return typeof markdown === "string" ? { markdown } : null;
}
