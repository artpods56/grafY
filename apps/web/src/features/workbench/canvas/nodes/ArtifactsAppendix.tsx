"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";

import {
  artifactContentUrl,
  type ArtifactSummary,
  type ArtifactTypeSpec,
  type RunPortOutput,
} from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { ArtifactViewerInteractionContext } from "../artifact-interactions";
import {
  META_ARTIFACT_RENDERER,
  PrettyValue,
  rendererFor,
} from "./artifact-renderers";
import { schemaTypeLabel } from "./type-inspector";
import { writeArtifactDrop } from "../../model/artifact-drop";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const EAGER_JSON_PREVIEW_BYTE_LIMIT = 512 * 1_024;

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
    return candidateSchema
      ? schemaCandidates(candidateSchema, root)
      : [];
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

  const variant = variants[0];
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
  if (
    itemVariants.length !== 1 ||
    !["string", "integer", "number", "boolean"].includes(
      String(itemVariants[0].type),
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
    requests.map(async (request) => [
      request.artifactId,
      await fetchJsonPayload(request),
    ] as const),
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

function valueAtPath(
  value: unknown,
  path: readonly string[],
): unknown {
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
  onFocusedArtifactChange?: (artifact: ArtifactSummary | null) => void;
}) {
  const { workspace } = useWorkspaceContext();
  const artifacts = output.artifacts;
  const sequence = output.kind === "sequence";
  const [index, setIndex] = React.useState(0);
  const [localModeChoice, setLocalModeChoice] =
    React.useState<string | null>(null);
  const modeChoice = controlledModeChoice === undefined
    ? localModeChoice
    : controlledModeChoice;
  const [localField, setLocalField] = React.useState("");
  const feedPath = feedProjection?.path.length ? feedProjection.path : null;
  const fieldControlledByEdge = feedPath != null;
  const [requestedPayloadArtifactId, setRequestedPayloadArtifactId] =
    React.useState<string | null>(null);

  const focusedIndex = Math.min(index, artifacts.length - 1);
  const active = artifacts[focusedIndex];
  const activeContentUrl = artifactContentUrl(workspace.id, active.content_url);

  React.useEffect(() => {
    onFocusedArtifactChange?.(active ?? null);
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
  const rendererOwnsPayload = tableArtifact || geoArtifact;
  const activeJsonSizeIsBounded =
    active.byte_size != null &&
    active.byte_size <= EAGER_JSON_PREVIEW_BYTE_LIMIT;
  const payloadDeferred =
    !rendererOwnsPayload &&
    active.content_type === "application/json" &&
    !activeJsonSizeIsBounded &&
    requestedPayloadArtifactId !== active.artifact_id;
  const activePayloadKey: ArtifactPayloadKey | null =
    !rendererOwnsPayload &&
    !payloadDeferred &&
    active.content_type === "application/json" &&
    activeContentUrl
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
  const explicitPayloadLoading =
    requestedPayloadArtifactId === active.artifact_id && activePayloadLoading;

  const artifactType = artifactTypes.find(
    (candidate) =>
      candidate.key.id === active.artifact_type &&
      candidate.key.schema_version === active.schema_version,
  );
  const candidateFields =
    sequence &&
    !geoArtifact &&
    active.content_type === "application/json" &&
    activeContentUrl
      ? projectableFields(artifactType)
      : [];
  const projectionPayloadByteSize = artifacts.reduce(
    (total, artifact) => total + (artifact.byte_size ?? 0),
    0,
  );
  const projectionPayloadsAreBounded =
    artifacts.every(
      (artifact) =>
        artifact.content_type === "application/json" &&
        artifact.byte_size != null,
    ) && projectionPayloadByteSize <= EAGER_JSON_PREVIEW_BYTE_LIMIT;
  const fields = projectionPayloadsAreBounded ? candidateFields : [];
  const feedProjectionDeferred =
    fieldControlledByEdge && sequence && !projectionPayloadsAreBounded;
  const projectionDeferred =
    feedProjectionDeferred ||
    (!fieldControlledByEdge &&
      candidateFields.length > 0 &&
      !projectionPayloadsAreBounded);
  const localSelectedField = fields.find(
    (option) => option.name === localField,
  );
  const edgeTopLevelField =
    feedPath?.length === 1 && sequence && !feedProjectionDeferred
      ? fields.find((option) => option.name === feedPath[0]) ??
        (feedPath[0]
          ? { name: feedPath[0], type: "unknown" }
          : undefined)
      : undefined;
  const selectedField = fieldControlledByEdge
    ? edgeTopLevelField
    : localSelectedField;
  const usesPathProjection =
    fieldControlledByEdge &&
    feedPath != null &&
    !feedProjectionDeferred &&
    !edgeTopLevelField &&
    sequence;
  const singleFeedProjection =
    fieldControlledByEdge && feedPath != null && !sequence;

  const projectionRequests =
    selectedField || usesPathProjection
      ? artifacts.flatMap((artifact) => {
          const url =
            artifact.content_type === "application/json"
              ? artifactContentUrl(workspace.id, artifact.content_url)
              : null;
          return url
            ? [{ artifactId: artifact.artifact_id, url }]
            : [];
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

  const jsonPayloadMissing =
    !rendererOwnsPayload &&
    active.content_type === "application/json" &&
    !activeContentUrl;
  const jsonPayloadFailed =
    !rendererOwnsPayload &&
    active.content_type === "application/json" &&
    Boolean(activePayloadError);
  const renderer = jsonPayloadMissing || jsonPayloadFailed || payloadDeferred
    ? META_ARTIFACT_RENDERER
    : rendererFor(active, activePayload);
  const mode =
    modeChoice && renderer.modes.includes(modeChoice)
      ? modeChoice
      : renderer.modes[0];
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
      (singleFeedProjection &&
        (Boolean(activePayloadError) || jsonPayloadMissing)));
  const visibleModes = showingFeedProjection
    ? projectionFallback
      ? META_ARTIFACT_RENDERER.modes
      : projectionModes
    : activePayloadLoading || payloadDeferred
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
  let payloadLoadingNotice =
    "This JSON artifact is not loaded automatically because its size is unknown.";
  if (explicitPayloadLoading) {
    payloadLoadingNotice = "Loading the complete JSON artifact…";
  } else if (active.byte_size != null) {
    const sizeMegabytes = (active.byte_size / (1_024 * 1_024)).toFixed(1);
    payloadLoadingNotice =
      `This JSON artifact is not loaded automatically (${sizeMegabytes} MB).`;
  }
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
              const selectedMode = showingFeedProjection ? projectionMode : mode;
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
      {projectionDeferred ? (
        <span {...stylex.props(s.notice)}>
          {fieldControlledByEdge
            ? `Field preview for .${feedPath?.join(".")} is disabled because this sequence is too large to load safely in the browser.`
            : "Field projection is disabled because this sequence is too large to load safely in the browser."}
        </span>
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
            (singleFeedProjection &&
              (activePayloadLoading || payloadDeferred)) ? (
              <span role="status" aria-live="polite" {...stylex.props(s.notice)}>
                Loading projected values…
              </span>
            ) : projectionError ||
              projectionMissingContent ||
              (singleFeedProjection &&
                (Boolean(activePayloadError) || jsonPayloadMissing)) ? (
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
                  artifact={active}
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
            {payloadDeferred || explicitPayloadLoading ? (
              <div {...stylex.props(s.notice)}>
                <p>{payloadLoadingNotice}</p>
                <button
                  type="button"
                  disabled={explicitPayloadLoading}
                  {...nodeInteractionProps(stylex.props(s.modeButton))}
                  onClick={() => setRequestedPayloadArtifactId(active.artifact_id)}
                >
                  {explicitPayloadLoading ? "Loading…" : "Load complete JSON"}
                </button>
                {explicitPayloadLoading ? (
                  <span role="status" aria-live="polite">
                    Loading complete JSON…
                  </span>
                ) : null}
              </div>
            ) : activePayloadLoading ? (
              <p role="status" aria-live="polite" {...stylex.props(s.notice)}>
                Loading complete JSON…
              </p>
            ) : activePayloadError || jsonPayloadMissing ? (
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
            {activePayloadLoading || payloadDeferred ? null : (
              <renderer.Component
                artifact={active}
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
