/** How much of the bytes the viewer reads before it stops. */
export const TEXT_HEAD_BYTE_LIMIT = 64 * 1_024;

export interface TextHead {
  text: string;
  truncated: boolean;
}

/**
 * Reads the head of a response and returns it as text, or null when the bytes
 * are not text: invalid UTF-8 or a NUL byte. Bytes are what decide, not the
 * content type, because a `file.blob@1` carries no usable one.
 */
export async function readTextHead(
  url: string,
  limit = TEXT_HEAD_BYTE_LIMIT,
): Promise<TextHead | null> {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`Could not load artifact content: ${response.status}`);
  }
  const reader = response.body?.getReader();
  if (!reader)
    return decodeText(new Uint8Array(await response.arrayBuffer()), limit);

  const chunks: Uint8Array[] = [];
  let length = 0;
  while (length <= limit) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    length += value.byteLength;
  }
  void reader.cancel();

  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return decodeText(bytes, limit);
}

function decodeText(bytes: Uint8Array, limit: number): TextHead | null {
  const truncated = bytes.byteLength > limit;
  const head = truncated ? bytes.subarray(0, limit) : bytes;
  if (head.includes(0)) return null;
  try {
    // A cut multibyte character at the limit is not corruption, so only a
    // complete body is decoded to the end.
    const text = new TextDecoder("utf-8", { fatal: true }).decode(head, {
      stream: truncated,
    });
    return { text, truncated };
  } catch {
    return null;
  }
}

/**
 * Indents a JSON document; any other text comes back unchanged. With
 * `expandEmbeddedJson`, a string value that is itself a JSON object or array
 * (a text artifact carrying serialized JSON) is shown as that JSON, not as one
 * escaped line.
 */
export function formatTextHead(
  head: TextHead,
  { expandEmbeddedJson = false }: { expandEmbeddedJson?: boolean } = {},
): string {
  if (head.truncated) return head.text;
  try {
    const value: unknown = JSON.parse(head.text);
    return JSON.stringify(
      expandEmbeddedJson ? expandJsonStrings(value) : value,
      null,
      2,
    );
  } catch {
    return head.text;
  }
}

function expandJsonStrings(value: unknown): unknown {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!/^[[{]/.test(trimmed)) return value;
    try {
      return expandJsonStrings(JSON.parse(trimmed));
    } catch {
      return value;
    }
  }
  if (Array.isArray(value)) return value.map(expandJsonStrings);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [
        key,
        expandJsonStrings(entry),
      ]),
    );
  }
  return value;
}
