/** Generates workbench IDs on HTTPS, localhost, and plain HTTP LAN origins. */
export function createUuid(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  // Set the version and variant bits while mapping, so every byte is read
  // through the callback parameter instead of an out-of-range index.
  const hex = Array.from(bytes, (byte, index) => {
    const shaped =
      index === 6
        ? (byte & 0x0f) | 0x40
        : index === 8
          ? (byte & 0x3f) | 0x80
          : byte;
    return shaped.toString(16).padStart(2, "0");
  }).join("");

  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
