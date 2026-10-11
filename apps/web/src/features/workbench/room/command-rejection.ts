const MISSING_ENTITY_CODES = new Set([
  "missing_node",
  "missing_edge",
  "missing_origin",
  "missing_viewer",
  "missing_annotation",
]);

const DUPLICATE_ENTITY_CODES = new Set([
  "duplicate_node",
  "duplicate_edge",
  "duplicate_origin",
]);

/**
 * Say what a rejected command means in terms a person can act on.
 *
 * The room reloads the head after every rejection, so the text says the latest
 * graph is back. Codes this client does not name fall through to the server's
 * own detail.
 */
export function describeCommandRejection(message: {
  readonly error_code: string;
  readonly detail: string;
}): string {
  if (message.error_code === "field_conflict") {
    return "Someone else changed this at the same time. The latest graph has been reloaded.";
  }
  if (MISSING_ENTITY_CODES.has(message.error_code)) {
    return "Something you edited was removed by someone else. The latest graph has been reloaded.";
  }
  if (DUPLICATE_ENTITY_CODES.has(message.error_code)) {
    return "That item already exists. The latest graph has been reloaded.";
  }
  return message.detail || "A collaborative edit was rejected.";
}
