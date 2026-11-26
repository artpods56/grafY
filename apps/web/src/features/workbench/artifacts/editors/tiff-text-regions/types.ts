/**
 * The `ocr.tiff_text_regions@1` payload, in the shape the editor works with.
 *
 * The wire shape is fixed by two Pydantic models, both of them `extra="forbid"`:
 * `TiffTextRegions` in `plugins/map_toponyms/.../text_regions.py` and `TextRegion`
 * in `libs/core/.../contracts/ocr.py`. A region of the *recognized* artifact
 * (`ocr.tiff_recognized_text@1`, `tiff_recognition.py`) is a `TextRegion` plus a
 * nullable `reading` of `{text, confidence, model}`, which is why a transcription
 * lives in one of two places and this module remembers which one it found.
 *
 * Nothing here is allowed to lose data it does not understand. An editor writes a
 * new version over a durable, digest-addressed artifact, so a field the editor has
 * no control for must still come back out of the serializer untouched — that is
 * what `extra`, `sourceExtra`, `windowExtra` and `readingExtra` are for, and why
 * they hold `unknown` rather than a copy of every key the contract happens to have
 * today.
 */

export type PixelPoint = readonly [number, number];

/** A region's transcription, whichever wire key carried it. */
export type RegionReading = {
  readonly text: string;
  /** The recognizer's self-report, 0…1; null when nothing scored this text. */
  readonly confidence: number | null;
};

/** Where a region's transcription is written back: `text`/`score`, or `reading`. */
export type RegionReadingField = "text" | "reading";

export type EditableTextRegion = {
  /** Full-resolution page pixels. Closed implicitly, as the contract has it. */
  readonly polygon: readonly PixelPoint[];
  /** Null when the region carries no transcription at all. */
  readonly reading: RegionReading | null;
  readonly readingField: RegionReadingField;
  /** Region keys outside the editor's reach (`text`/`score` when a `reading` won), verbatim. */
  readonly extra: Readonly<Record<string, unknown>>;
  /** Keys inside `reading` outside the editor's reach — `model` above all, verbatim. */
  readonly readingExtra: Readonly<Record<string, unknown>>;
};

/** `TiffPixelWindow` in the plugin: the area of the page a detector was pointed at. */
export type TiffPixelWindow = {
  readonly page: number;
  readonly col: number;
  readonly row: number;
  readonly width: number;
  readonly height: number;
};

/** `Ref[TiffFile]`: the scan these regions are drawn on. Only its identity is modelled. */
export type TiffSourceReference = {
  readonly artifact_id: string;
  readonly artifact_type: string;
  readonly schema_version: number;
};

export type TiffTextRegionsPayload = {
  readonly source: TiffSourceReference;
  readonly sourceExtra: Readonly<Record<string, unknown>>;
  readonly window: TiffPixelWindow;
  readonly windowExtra: Readonly<Record<string, unknown>>;
  readonly regions: readonly EditableTextRegion[];
  /** Payload keys this schema version does not declare, verbatim. */
  readonly extra: Readonly<Record<string, unknown>>;
};

export type ParseTiffTextRegionsResult =
  | { readonly ok: true; readonly payload: TiffTextRegionsPayload }
  | { readonly ok: false; readonly reason: string };

/** A polygon is a closed area; the contract refuses fewer than this. */
export const MIN_POLYGON_VERTICES = 3;

const READING_KEYS = new Set(["text", "confidence"]);
/**
 * Which region keys the editor takes over. A region whose transcription is a
 * `reading` keeps its own `text` and `score` — they belong to the detector, and a
 * person editing the recognizer's words has no business overwriting them.
 */
const REGION_READING_KEYS = new Set(["polygon", "reading"]);
const REGION_TEXT_KEYS = new Set(["polygon", "text", "score"]);
const SOURCE_MODELLED_KEYS = new Set([
  "artifact_id",
  "artifact_type",
  "schema_version",
]);
const WINDOW_MODELLED_KEYS = new Set(["page", "col", "row", "width", "height"]);
const PAYLOAD_MODELLED_KEYS = new Set(["source", "window", "regions"]);

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** Every key of `source` except the ones `keep` names. */
function restKeys(
  source: Readonly<Record<string, unknown>>,
  keep: ReadonlySet<string>,
): Record<string, unknown> {
  const rest: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (keep.has(key)) continue;
    rest[key] = value;
  }
  return rest;
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return null;
  }
  return value;
}

function parsePoint(value: unknown): PixelPoint | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [x, y] = value;
  if (
    typeof x !== "number" ||
    typeof y !== "number" ||
    !Number.isFinite(x) ||
    !Number.isFinite(y) ||
    x < 0 ||
    y < 0
  ) {
    return null;
  }
  return [x, y];
}

function parseReading(value: unknown): RegionReading | null {
  const reading = record(value);
  if (!reading || typeof reading.text !== "string") return null;
  return { text: reading.text, confidence: finiteOrNull(reading.confidence) };
}

function parseRegion(value: unknown): EditableTextRegion | null {
  const region = record(value);
  if (!region || !Array.isArray(region.polygon)) return null;
  const polygon: PixelPoint[] = [];
  for (const vertex of region.polygon) {
    const point = parsePoint(vertex);
    if (!point) return null;
    polygon.push(point);
  }
  if (polygon.length < MIN_POLYGON_VERTICES) return null;

  const extra = restKeys(
    region,
    "reading" in region ? REGION_READING_KEYS : REGION_TEXT_KEYS,
  );
  // A `reading` key at all means a recognizer spoke for this region, so its text
  // is the transcription a person reads and `text`/`score` stay in `extra`.
  if ("reading" in region) {
    const reading = parseReading(region.reading);
    const source = record(region.reading);
    return {
      polygon,
      reading,
      readingField: "reading",
      extra,
      readingExtra: source ? restKeys(source, READING_KEYS) : {},
    };
  }
  const text = typeof region.text === "string" ? region.text : null;
  const confidence = finiteOrNull(region.score);
  return {
    polygon,
    reading: text === null ? null : { text, confidence },
    readingField: "text",
    extra,
    readingExtra: {},
  };
}

/** Read a stored artifact payload into the editor's model, or say why it cannot. */
export function parseTiffTextRegionsPayload(
  raw: unknown,
): ParseTiffTextRegionsResult {
  const payload = record(raw);
  if (!payload) {
    return {
      ok: false,
      reason: "This artifact is not a set of TIFF text regions.",
    };
  }
  const source = record(payload.source);
  if (
    !source ||
    typeof source.artifact_id !== "string" ||
    !source.artifact_id
  ) {
    return {
      ok: false,
      reason:
        "These text regions name no source scan, so they cannot be edited.",
    };
  }
  const window = record(payload.window);
  if (!window || !Array.isArray(payload.regions)) {
    return {
      ok: false,
      reason:
        "These text regions are missing their page window or region list.",
    };
  }
  const page = nonNegativeInteger(window.page);
  const col = nonNegativeInteger(window.col);
  const row = nonNegativeInteger(window.row);
  const width = nonNegativeInteger(window.width);
  const height = nonNegativeInteger(window.height);
  if (page === null || col === null || row === null || width === null) {
    return {
      ok: false,
      reason: "These text regions describe an invalid page window.",
    };
  }
  if (height === null || height <= 0) {
    return {
      ok: false,
      reason: "These text regions describe an empty page window.",
    };
  }

  const regions: EditableTextRegion[] = [];
  for (const [index, value] of payload.regions.entries()) {
    const region = parseRegion(value);
    if (!region) {
      return {
        ok: false,
        reason: `Region ${index + 1} has no polygon this editor can draw.`,
      };
    }
    regions.push(region);
  }

  const schemaVersion =
    typeof source.schema_version === "number" ? source.schema_version : 1;
  const artifactType =
    typeof source.artifact_type === "string"
      ? source.artifact_type
      : "file.tiff";

  return {
    ok: true,
    payload: {
      source: {
        artifact_id: source.artifact_id,
        artifact_type: artifactType,
        schema_version: schemaVersion,
      },
      sourceExtra: restKeys(source, SOURCE_MODELLED_KEYS),
      window: { page, col, row, width, height },
      windowExtra: restKeys(window, WINDOW_MODELLED_KEYS),
      regions,
      extra: restKeys(payload, PAYLOAD_MODELLED_KEYS),
    },
  };
}

/**
 * A region the editor drew.
 *
 * The caller supplies the wire shape even when the page has no existing regions.
 */
export function newEditableRegion(
  polygon: readonly PixelPoint[],
  readingField: RegionReadingField,
): EditableTextRegion {
  return {
    polygon,
    reading: null,
    readingField,
    extra: {},
    readingExtra: {},
  };
}

function serializeRegion(region: EditableTextRegion): Record<string, unknown> {
  const serialized: Record<string, unknown> = { ...region.extra };
  serialized.polygon = region.polygon.map(([x, y]) => [x, y] as PixelPoint);
  if (region.readingField === "reading") {
    // `model` names the recognizer the contract says wrote these words. One that
    // came with the region is kept exactly as it came — a correction of the words
    // is not a correction of who read them — and words with no recognizer behind
    // them at all are named as the editor's own.
    serialized.reading =
      region.reading === null
        ? null
        : {
            model: "manual",
            ...region.readingExtra,
            text: region.reading.text,
            confidence: region.reading.confidence,
          };
    return serialized;
  }
  serialized.text = region.reading?.text ?? null;
  serialized.score = region.reading?.confidence ?? null;
  return serialized;
}

/** Compare only changed regions. Every editor action preserves the source and window. */
export function sameTiffRegions(
  previous: readonly EditableTextRegion[],
  next: readonly EditableTextRegion[],
): boolean {
  return (
    previous === next ||
    (previous.length === next.length &&
      next.every((region, index) => {
        const old = previous[index];
        return (
          region === old ||
          (old !== undefined &&
            JSON.stringify(serializeRegion(region)) ===
              JSON.stringify(serializeRegion(old)))
        );
      }))
  );
}

/** Anything the editor was built around a state for, or the payload on its own. */
export type SerializableTiffTextRegions =
  TiffTextRegionsPayload | { readonly payload: TiffTextRegionsPayload };

function payloadFrom(
  state: SerializableTiffTextRegions,
): TiffTextRegionsPayload {
  if ("payload" in state) return state.payload;
  return state;
}

/**
 * Write the editor's model back to the artifact payload.
 *
 * Accepts the payload or a whole editor state so a call site cannot pick the wrong
 * one by hand. `source` and `window` are written from what parse kept, so a save
 * moves only the regions.
 */
export function serializeTiffTextRegionsPayload(
  state: SerializableTiffTextRegions,
): Record<string, unknown> {
  const payload = payloadFrom(state);
  const serialized: Record<string, unknown> = { ...payload.extra };
  serialized.source = {
    ...payload.sourceExtra,
    artifact_id: payload.source.artifact_id,
    artifact_type: payload.source.artifact_type,
    schema_version: payload.source.schema_version,
  };
  serialized.window = {
    ...payload.windowExtra,
    page: payload.window.page,
    col: payload.window.col,
    row: payload.window.row,
    width: payload.window.width,
    height: payload.window.height,
  };
  serialized.regions = payload.regions.map(serializeRegion);
  return serialized;
}

/** The text a region shows in the list and the inspector; blank when it has none. */
export function regionText(region: EditableTextRegion): string {
  return region.reading?.text ?? "";
}
