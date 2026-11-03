"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";

import {
  artifactInlineContentUrl,
  type ArtifactSummary,
  type ArtifactTypeSpec,
  type RunPortArtifact,
  type RunPortOutput,
} from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeFor, declaredArtifactContentType } from "../artifact-card";
import type { ArtifactViewerInteractionContext } from "../artifact-interactions";
import { PrettyValue } from "./artifact-renderers/pretty-value";
import {
  META_ARTIFACT_RENDERER,
  rendererFor,
} from "./artifact-renderers/registry";
import { schemaTypeLabel } from "./type-inspector";
import { writeArtifactDrop } from "../../model/artifact-drop";
import { BLOB_ARTIFACT_NOTICE, isBlobArtifact } from "../../model/blob-notice";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

/**
 * The renderer view of one artifact a stored result names.
 *
 * A stored result carries a *reference* — id, artifact type, schema version,
 * content hash — and never a content type, a byte size or inline text: those
 * belonged to the run that produced them. So the card resolves the bytes
 * through the artifact route, which serves them with their stored content type,
 * and reads the only declarations that remain from the artifact-type catalog:
 * how the payload is bundled, and what a download would be called.
 */
export function storedArtifactView(
  workspaceId: string,
  artifact: RunPortArtifact,
  artifactType: ArtifactTypeSpec | undefined,
): ArtifactSummary {
  return {
    artifact_id: artifact.artifact_id,
    artifact_type: artifact.artifact_type,
    schema_version: artifact.schema_version,
    content_type:
      declaredArtifactContentType(artifactType) ?? "application/octet-stream",
    content_url: artifactInlineContentUrl(workspaceId, artifact.artifact_id),
    ...(artifact.content_hash ? { sha256: artifact.content_hash } : {}),
    ...(artifactType?.export_formats
      ? { download_formats: artifactType.export_formats }
      : {}),
    // No `byte_size` and no `metadata`: a reference carries neither, and the
    // renderers that take this view show no size and no uploaded filename.
  };
}

/**
 * Whether the card should read this artifact's bytes as JSON before rendering.
 * The catalog's bundle contract is what still says how a payload is stored.
 */
function payloadIsJson(artifactType: ArtifactTypeSpec | undefined): boolean {
  return declaredArtifactContentType(artifactType) === "application/json";
}

const s = stylex.create({
  section: { display: "grid", gap: "8px" },
  headRow: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
  },
  headTitle: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.06em",
    textTransform: "uppercase",
  },
  kindBadge: {
    padding: "1px 7px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
  },
  modeToggle: {
    marginLeft: "auto",
    display: "flex",
    gap: "2px",
    padding: "2px",
    borderRadius: "8px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  modeButton: {
    height: "20px",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorSubtle,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 700,
  },
  modeButtonActive: {
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
    color: tokens.colorTextEmphasis,
  },
  fieldSelect: {
    width: "100%",
    height: "24px",
    paddingInline: "7px",
    borderWidth: 0,
    borderRadius: "7px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "10px",
  },
  pager: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  pageChip: {
    minWidth: "22px",
    height: "22px",
    paddingInline: "4px",
    flexShrink: 0,
    borderWidth: 0,
    borderRadius: "7px",
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontFamily: MONO,
    fontSize: "10px",
  },
  pageChipActive: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
    fontWeight: 700,
  },
  ellipsis: {
    paddingInline: "1px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
  },
  indexGroup: {
    marginLeft: "auto",
    display: "flex",
    alignItems: "center",
    gap: "4px",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
  },
  indexInput: {
    width: "36px",
    height: "22px",
    paddingInline: "5px",
    borderWidth: 0,
    borderRadius: "7px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "10px",
    textAlign: "center",
    appearance: "textfield",
  },
  body: {
    maxHeight: "230px",
    overflowY: "auto",
    overflowX: "auto",
    padding: "9px 10px",
    borderRadius: "10px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  tableBody: {
    maxHeight: "none",
    overflow: "visible",
    padding: 0,
    borderRadius: 0,
    backgroundColor: "transparent",
  },
  raw: {
    margin: 0,
    fontFamily: MONO,
    fontSize: "10px",
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  projectedList: { display: "grid", gap: "5px" },
  projectedRow: {
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    alignItems: "baseline",
    gap: "6px",
  },
  projectedIndex: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "10px",
  },
  projectionType: {
    color: tokens.colorAccent,
    fontFamily: MONO,
    fontSize: "10px",
  },
  notice: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.45,
  },
  noticeError: { color: tokens.colorDanger },
});

function nodeInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

interface FieldOption {
  name: string;
  type: string;
}

interface JsonPayloadRequest {
  artifactId: string;
  url: string;
}

type ArtifactPayloadKey = readonly ["artifact-json", JsonPayloadRequest];
type SequencePayloadKey = readonly [
  "artifact-json-sequence",
  string,
  readonly JsonPayloadRequest[],
];

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function schemaCandidates(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): Record<string, unknown>[] {
  let resolved = schema;
  const reference = resolved.$ref;
  if (typeof reference === "string" && reference.startsWith("#/$defs/")) {
    const definitions = record(root.$defs);
    resolved =
      record(definitions?.[reference.slice("#/$defs/".length)]) ?? resolved;
  }
  if (!Array.isArray(resolved.anyOf)) return [resolved];
  return resolved.anyOf.flatMap((candidate) => {
    const candidateSchema = record(candidate);
    return candidateSchema ? schemaCandidates(candidateSchema, root) : [];
  });
}

function projectionFieldType(
  schema: Record<string, unknown>,
  root: Record<string, unknown>,
): string | null {
  const variants = schemaCandidates(schema, root).filter(
    (candidate) => candidate.type !== "null",
  );
  if (variants.length !== 1) return null;

  const [variant] = variants;
  if (!variant) return null;
  if (
    variant.type === "string" ||
    variant.type === "integer" ||
    variant.type === "number" ||
    variant.type === "boolean"
  ) {
    return schemaTypeLabel(schema, root);
  }
  if (variant.type !== "array") return null;

  const items = record(variant.items);
  if (!items) return null;
  const itemVariants = schemaCandidates(items, root).filter(
    (candidate) => candidate.type !== "null",
  );
  const [itemVariant] = itemVariants;
  if (
    itemVariants.length !== 1 ||
    !itemVariant ||
    !["string", "integer", "number", "boolean"].includes(
      String(itemVariant.type),
    )
  ) {
    return null;
  }
  return schemaTypeLabel(schema, root);
}

async function fetchJsonPayload(request: JsonPayloadRequest): Promise<unknown> {
  const response = await fetch(request.url, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(
      `Could not load JSON payload for artifact ${request.artifactId}: ${response.status} ${response.statusText}`,
    );
  }
  try {
    return await response.json();
  } catch (error) {
    throw new Error(
      `Could not parse JSON payload for artifact ${request.artifactId}`,
      { cause: error },
    );
  }
}

async function loadArtifactPayload([
  ,
  request,
]: ArtifactPayloadKey): Promise<unknown> {
  return fetchJsonPayload(request);
}

async function loadSequencePayloads([
  ,
  ,
  requests,
]: SequencePayloadKey): Promise<Record<string, unknown>> {
  const entries = await Promise.all(
    requests.map(
      async (request) =>
        [request.artifactId, await fetchJsonPayload(request)] as const,
    ),
  );
  return Object.fromEntries(entries);
}

function projectableFields(spec: ArtifactTypeSpec | undefined): FieldOption[] {
  const root = record(spec?.payload_schema);
  const properties = record(root?.properties);
  if (!root || !properties) return [];

  return Object.entries(properties).flatMap(([name, rawProperty]) => {
    const property = record(rawProperty);
    if (!property) return [];
    const type = projectionFieldType(property, root);
    return type ? [{ name, type }] : [];
  });
}

function valueAtPath(value: unknown, path: readonly string[]): unknown {
  let current = value;
  for (const segment of path) {
    const asRecord = record(current);
    if (!asRecord || !(segment in asRecord)) return undefined;
    current = asRecord[segment];
  }
  return current;
}

function pageWindow(count: number, current: number): (number | "gap")[] {
  if (count <= 7) {
    return Array.from({ length: count }, (_, index) => index + 1);
  }

  const pages = new Set([
    1,
    2,
    current - 1,
    current,
    current + 1,
    count - 1,
    count,
  ]);
  const sorted = [...pages]
    .filter((page) => page >= 1 && page <= count)
    .sort((left, right) => left - right);
  const result: (number | "gap")[] = [];
  let previous = 0;
  for (const page of sorted) {
    if (page - previous > 1) result.push("gap");
    result.push(page);
    previous = page;
  }
  return result;
}

function SequencePager({
  count,
  index,
  onChange,
}: {
  count: number;
  index: number;
  onChange: (index: number) => void;
}) {
  const clamp = (value: number) => Math.min(count - 1, Math.max(0, value));

  return (
    <div {...stylex.props(s.pager)}>
      {pageWindow(count, index + 1).map((page, position) =>
        page === "gap" ? (
          <span key={`gap-${position}`} {...stylex.props(s.ellipsis)}>
            …
          </span>
        ) : (
          <button
            key={page}
            type="button"
            aria-label={`Show item ${page}`}
            aria-current={page === index + 1 ? "page" : undefined}
            {...nodeInteractionProps(
              stylex.props(
                s.pageChip,
                page === index + 1 ? s.pageChipActive : null,
              ),
            )}
            onClick={() => onChange(page - 1)}
          >
            {page}
          </button>
        ),
      )}
      <label {...stylex.props(s.indexGroup)}>
        <input
          type="number"
          min={1}
          max={count}
          value={index + 1}
          aria-label="Item index"
          {...nodeInteractionProps(stylex.props(s.indexInput))}
          onChange={(event) => {
            const value = Number.parseInt(event.currentTarget.value, 10);
            if (!Number.isNaN(value)) onChange(clamp(value - 1));
          }}
        />
        / {count}
      </label>
    </div>
  );
}

export function ArtifactPortPreview({
  output,
  artifactTypes,
  previewHeight,
  modeChoice: controlledModeChoice,
  onModeChoiceChange,
  feedProjection = null,
  interaction,
  onFocusedArtifactChange,
}: {
  output: RunPortOutput;
  artifactTypes: readonly ArtifactTypeSpec[];
  previewHeight: number;
  modeChoice?: string | null;
  onModeChoiceChange?: (mode: string) => void;
  /** Edge-owned feed: whole output when null/empty, else project along path. */
  feedProjection?: { path: readonly string[] } | null;
  interaction?: ArtifactViewerInteractionContext;
  /** The stored reference the card is showing, for the card's own actions. */
  onFocusedArtifactChange?: (artifact: RunPortArtifact | null) => void;
}) {
  const { workspace } = useWorkspaceContext();
  const artifacts = output.artifacts;
  const sequence = output.kind === "sequence";
  const [index, setIndex] = React.useState(0);
  const [localModeChoice, setLocalModeChoice] = React.useState<string | null>(
    null,
  );
  const modeChoice =
    controlledModeChoice === undefined ? localModeChoice : controlledModeChoice;
  const [localField, setLocalField] = React.useState("");
  const feedPath = feedProjection?.path.length ? feedProjection.path : null;
  const fieldControlledByEdge = feedPath != null;

  const focusedIndex = Math.min(index, artifacts.length - 1);
  const active = artifacts[focusedIndex];
  // Every caller renders this preview only for an output that has artifacts;
  // an empty one has nothing to focus and no card to paint.
  if (!active) {
    throw new Error(
      `ArtifactPortPreview needs at least one artifact (port ${output.port})`,
    );
  }
  const artifactType = artifactTypeFor(active, artifactTypes);
  const activeView = storedArtifactView(workspace.id, active, artifactType);
  const activeContentUrl = activeView.content_url ?? null;
  const activeJson = payloadIsJson(artifactType);

  React.useEffect(() => {
    onFocusedArtifactChange?.(active);
  }, [active, onFocusedArtifactChange]);
  const tableArtifact =
    active.artifact_type === "table.data" && active.schema_version === 1;
  const geoArtifact =
    active.schema_version === 1 &&
    [
      "geo.feature_collection",
      "geo.raster_scan",
      "geo.map_layer",
      "geo.map_document",
    ].includes(active.artifact_type);
  // Table and map renderers read the paged endpoints for themselves; the card
  // only loads a whole JSON payload for the pretty and raw views.
  const rendererOwnsPayload = tableArtifact || geoArtifact;
  const activePayloadKey: ArtifactPayloadKey | null =
    !rendererOwnsPayload && activeJson && activeContentUrl
      ? [
          "artifact-json",
          { artifactId: active.artifact_id, url: activeContentUrl },
        ]
      : null;
  const {
    data: activePayload,
    error: activePayloadError,
    isLoading: activePayloadLoading,
  } = useSWR(activePayloadKey, loadArtifactPayload);

  const candidateFields =
    sequence && !geoArtifact && activeJson && activeContentUrl
      ? projectableFields(artifactType)
      : [];
  const fields = candidateFields;
  const localSelectedField = fields.find(
    (option) => option.name === localField,
  );
  const edgeTopLevelField =
    feedPath?.length === 1 && sequence
      ? (fields.find((option) => option.name === feedPath[0]) ??
        (feedPath[0] ? { name: feedPath[0], type: "unknown" } : undefined))
      : undefined;
  const selectedField = fieldControlledByEdge
    ? edgeTopLevelField
    : localSelectedField;
  const usesPathProjection =
    fieldControlledByEdge && feedPath != null && !edgeTopLevelField && sequence;
  const singleFeedProjection =
    fieldControlledByEdge && feedPath != null && !sequence;

  const projectionRequests =
    selectedField || usesPathProjection
      ? artifacts.flatMap((artifact) => {
          const url = activeJson
            ? artifactInlineContentUrl(workspace.id, artifact.artifact_id)
            : null;
          return url ? [{ artifactId: artifact.artifact_id, url }] : [];
        })
      : [];
  const projectionKey: SequencePayloadKey | null =
    (selectedField || usesPathProjection) &&
    projectionRequests.length === artifacts.length
      ? ["artifact-json-sequence", output.port, projectionRequests]
      : null;
  const {
    data: projectionPayloads,
    error: projectionError,
    isLoading: projectionLoading,
  } = useSWR(projectionKey, loadSequencePayloads);

  const jsonPayloadFailed =
    !rendererOwnsPayload && activeJson && Boolean(activePayloadError);
  const renderer = jsonPayloadFailed
    ? META_ARTIFACT_RENDERER
    : rendererFor(activeView, activePayload);
  const [firstMode] = renderer.modes;
  // Every renderer declares at least one mode; one with none has nothing to
  // ask its component to paint.
  if (!firstMode) {
    throw new Error(`Artifact renderer ${renderer.id} declares no modes`);
  }
  const mode =
    modeChoice && renderer.modes.includes(modeChoice) ? modeChoice : firstMode;
  const projectionModes = ["pretty", "raw"] as const;
  const projectionMode =
    modeChoice && projectionModes.includes(modeChoice as "pretty" | "raw")
      ? modeChoice
      : projectionModes[0];
  const showingFeedProjection = Boolean(
    selectedField || usesPathProjection || singleFeedProjection,
  );
  const projectionMissingContent =
    Boolean(selectedField || usesPathProjection) &&
    projectionRequests.length !== artifacts.length;
  const singleFeedValue =
    singleFeedProjection && feedPath && activePayload !== undefined
      ? valueAtPath(activePayload, feedPath)
      : undefined;
  const projectionFallback =
    showingFeedProjection &&
    (Boolean(projectionError) ||
      projectionMissingContent ||
      (singleFeedProjection && Boolean(activePayloadError)));
  const visibleModes = showingFeedProjection
    ? projectionFallback
      ? META_ARTIFACT_RENDERER.modes
      : projectionModes
    : activePayloadLoading
      ? []
      : renderer.modes;
  const projectedValues =
    selectedField || usesPathProjection
      ? projectionPayloads
        ? artifacts.map((artifact) => {
            const payload = projectionPayloads[artifact.artifact_id];
            if (usesPathProjection && feedPath) {
              return valueAtPath(payload, feedPath);
            }
            if (!selectedField) return undefined;
            return record(payload)?.[selectedField.name];
          })
        : null
      : singleFeedProjection
        ? [singleFeedValue]
        : null;
  const feedProjectionLabel = feedPath
    ? feedPath.join(".")
    : selectedField?.name;
  return (
    <section
      draggable
      onDragStart={(event) => {
        writeArtifactDrop(event.dataTransfer, output.value);
      }}
      {...stylex.props(s.section)}
    >
      <div {...stylex.props(s.headRow)}>
        <span {...stylex.props(s.headTitle)}>{output.port}</span>
        <span {...stylex.props(s.kindBadge)}>
          {sequence ? `sequence · ${artifacts.length}` : "single"}
        </span>
        {visibleModes.length > 1 ? (
          <div
            role="group"
            aria-label="Artifact view mode"
            {...stylex.props(s.modeToggle)}
          >
            {visibleModes.map((option) => {
              const selectedMode = showingFeedProjection
                ? projectionMode
                : mode;
              return (
                <button
                  key={option}
                  type="button"
                  aria-pressed={selectedMode === option}
                  {...nodeInteractionProps(
                    stylex.props(
                      s.modeButton,
                      selectedMode === option ? s.modeButtonActive : null,
                    ),
                  )}
                  onClick={() => {
                    if (controlledModeChoice === undefined) {
                      setLocalModeChoice(option);
                    }
                    onModeChoiceChange?.(option);
                  }}
                >
                  {option}
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
      {isBlobArtifact(active) ? (
        <span role="status" {...stylex.props(s.notice)}>
          {BLOB_ARTIFACT_NOTICE}
        </span>
      ) : null}
      {!fieldControlledByEdge && fields.length ? (
        <select
          aria-label="Project artifacts onto a field"
          value={localField}
          {...nodeInteractionProps(stylex.props(s.fieldSelect))}
          onChange={(event) => setLocalField(event.currentTarget.value)}
        >
          <option value="">whole objects</option>
          {fields.map((option) => (
            <option key={option.name} value={option.name}>
              map .{option.name} → list[{option.type}]
            </option>
          ))}
        </select>
      ) : null}
      {showingFeedProjection ? (
        <>
          <span {...stylex.props(s.projectionType)}>
            {sequence
              ? `list · .${feedProjectionLabel} · ${artifacts.length} items`
              : `.${feedProjectionLabel}`}
          </span>
          <div
            {...nodeInteractionProps(stylex.props(s.body))}
            style={{ maxHeight: previewHeight }}
          >
            {projectionLoading ||
            (singleFeedProjection && activePayloadLoading) ? (
              <span
                role="status"
                aria-live="polite"
                {...stylex.props(s.notice)}
              >
                Loading projected values…
              </span>
            ) : projectionError ||
              projectionMissingContent ||
              (singleFeedProjection && Boolean(activePayloadError)) ? (
              <>
                <p
                  role="alert"
                  title={
                    projectionError instanceof Error
                      ? projectionError.message
                      : activePayloadError instanceof Error
                        ? activePayloadError.message
                        : undefined
                  }
                  {...stylex.props(s.notice, s.noticeError)}
                >
                  Projection preview unavailable; showing artifact metadata.
                </p>
                <META_ARTIFACT_RENDERER.Component
                  artifact={activeView}
                  mode="meta"
                />
              </>
            ) : projectedValues ? (
              projectionMode === "raw" ? (
                <pre {...stylex.props(s.raw)}>
                  {JSON.stringify(
                    sequence ? projectedValues : projectedValues[0],
                    null,
                    2,
                  )}
                </pre>
              ) : sequence ? (
                <div {...stylex.props(s.projectedList)}>
                  {projectedValues.map((value, itemIndex) => (
                    <div key={itemIndex} {...stylex.props(s.projectedRow)}>
                      <span {...stylex.props(s.projectedIndex)}>
                        {String(itemIndex + 1).padStart(2, "0")}
                      </span>
                      <PrettyValue value={value ?? "—"} />
                    </div>
                  ))}
                </div>
              ) : (
                <PrettyValue value={projectedValues[0] ?? "—"} />
              )
            ) : null}
          </div>
        </>
      ) : (
        <>
          {sequence ? (
            <SequencePager
              count={artifacts.length}
              index={focusedIndex}
              onChange={setIndex}
            />
          ) : null}
          <div
            {...nodeInteractionProps(
              stylex.props(s.body, tableArtifact ? s.tableBody : null),
            )}
            style={{ maxHeight: tableArtifact ? undefined : previewHeight }}
          >
            {activePayloadLoading ? (
              <p role="status" aria-live="polite" {...stylex.props(s.notice)}>
                Loading complete JSON…
              </p>
            ) : activePayloadError ? (
              <p
                role="alert"
                title={
                  activePayloadError instanceof Error
                    ? activePayloadError.message
                    : undefined
                }
                {...stylex.props(s.notice, s.noticeError)}
              >
                JSON preview unavailable; showing artifact metadata.
              </p>
            ) : null}
            {activePayloadLoading ? null : (
              <renderer.Component
                artifact={activeView}
                payload={activePayload}
                mode={mode}
                availableHeight={previewHeight}
                interaction={interaction}
              />
            )}
          </div>
        </>
      )}
    </section>
  );
}
