"use client";

import { useCallback, useEffect, useMemo } from "react";
import useSWR from "swr";

import {
  createArtifact,
  createdArtifactToRef,
  type ArtifactRef,
} from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";

import {
  TiffArtifactView,
  type PixelPolygon,
  type TiffRegionEditorSession,
} from "../TiffArtifactView";
import {
  readTiffWindow,
  type TiffWindowSelection,
} from "../TiffWindowSelector";
import {
  TiffRegionsEditControls,
  type TiffRegionsEditControlsProps,
} from "../editors/tiff-text-regions/TiffRegionsEditControls";
import {
  parseTiffTextRegionsPayload,
  type TiffTextRegionsPayload,
} from "../editors/tiff-text-regions/types";
import type { TiffTextRegionsEditorAction } from "../editors/tiff-text-regions/tiff-text-regions-editor-reducer";
import { record } from "./payload";
import { reduceTiffTextEditSession } from "./tiff-text-edit-session";

function editingOverlay({ source, window, regions }: TiffTextRegionsPayload) {
  return {
    artifactId: source.artifact_id,
    page: window.page,
    bounds: window,
    polygons: regions.map((region) => region.polygon),
    readings: regions.map((region) =>
      region.readingField === "reading" ? (region.reading?.text ?? null) : null,
    ),
  };
}

function isPolygon(value: unknown): value is PixelPolygon {
  return (
    Array.isArray(value) &&
    value.length >= 3 &&
    value.every(
      (point: unknown) =>
        Array.isArray(point) &&
        point.length === 2 &&
        point.every(
          (coordinate: unknown) =>
            typeof coordinate === "number" &&
            Number.isFinite(coordinate) &&
            coordinate >= 0,
        ),
    )
  );
}

function overlayPayload(payload: unknown) {
  const value = record(payload);
  const artifactId = record(value?.source)?.artifact_id;
  const window = readTiffWindow(record(value?.window) ?? {});
  if (
    typeof artifactId !== "string" ||
    !window ||
    !Array.isArray(value?.regions)
  )
    return null;

  const polygons: PixelPolygon[] = [];
  const readings: (string | null)[] = [];
  let hasReadings = false;
  for (const region of value.regions) {
    const item = record(region);
    const polygon = item?.polygon;
    if (!isPolygon(polygon)) return null;
    polygons.push(polygon);
    const reading = record(item?.reading)?.text;
    readings.push(
      typeof reading === "string" && reading.trim() ? reading : null,
    );
    hasReadings ||= item !== null && "reading" in item;
  }
  return {
    artifactId,
    page: window.page,
    polygons,
    bounds: window,
    readings: hasReadings ? readings : undefined,
  };
}

async function fetchOverlay(url: string) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("Could not load text regions.");
  const rawPayload = record(await response.json());
  const overlay = overlayPayload(rawPayload);
  if (!rawPayload || !overlay) throw new Error("Invalid text regions.");
  return { url, rawPayload, overlay };
}

export function TiffTextArtifact({
  url,
  workspaceId,
  height,
  linkedWindow,
  recognized = false,
  onSize,
  artifactRef,
  editing = false,
  canEdit = false,
  onEditingChange,
  onSaveArtifact,
  EditControls = TiffRegionsEditControls,
  placeholder,
  viewportProps,
}: {
  /** The result to draw, or null while its producer has none that is current. */
  url: string | null;
  workspaceId: string;
  height: number;
  linkedWindow?: { artifactId: string; selection: TiffWindowSelection };
  recognized?: boolean;
  /** The linked scan's pixel size, once its tile pyramid describes it. */
  onSize?: (width: number, height: number) => void;
  artifactRef?: ArtifactRef;
  editing?: boolean;
  canEdit?: boolean;
  onEditingChange?: (editing: boolean) => void;
  onSaveArtifact?: (nextRef: ArtifactRef) => void;
  EditControls?: React.ComponentType<TiffRegionsEditControlsProps>;
  /** Shown while there is no result and no scan to keep open. */
  placeholder?: React.ReactNode;
  /** For the element holding the scan; a placeholder does not get them. */
  viewportProps?: React.ComponentProps<"div"> & {
    "data-cell-interactive-viewport"?: string;
  };
}) {
  // The previous result keeps the scan, and so the zoom and pan, while the next
  // one is on its way.
  const { data, error } = useSWR(url, fetchOverlay, { keepPreviousData: true });
  const [session, dispatch] = useEffectReducer(
    reduceTiffTextEditSession,
    { kind: "inactive" },
    (effect, send) => {
      void createArtifact(effect.workspaceId, {
        artifact_type: effect.artifact.artifact_type,
        schema_version: effect.artifact.schema_version,
        payload: effect.payload,
        derived_from_artifact_id: effect.artifact.artifact_id,
      }).then(
        (created) => {
          send({ type: "saved", effect });
          onSaveArtifact?.(createdArtifactToRef(created));
        },
        (failure: unknown) =>
          send({
            type: "save_failed",
            effect,
            message:
              failure instanceof Error
                ? failure.message
                : "Could not save text regions.",
          }),
      );
    },
  );
  const parsed = useMemo(() => {
    if (editing && canEdit && data && data.url === url) {
      return parseTiffTextRegionsPayload(data.rawPayload);
    }
    return null;
  }, [editing, canEdit, data, url]);

  useEffect(() => {
    if (parsed?.ok && url) {
      dispatch({
        type: "start",
        url,
        payload: parsed.payload,
        readingField: recognized ? "reading" : "text",
      });
    } else {
      dispatch({ type: "stop" });
    }
  }, [dispatch, parsed, recognized, url]);

  const activeSession =
    editing && canEdit && session.kind !== "inactive" && session.url === url
      ? session
      : null;
  const state = activeSession?.editor ?? null;
  const dispatchEdit = useCallback(
    (action: TiffTextRegionsEditorAction) => dispatch({ type: "edit", action }),
    [dispatch],
  );
  const editPayload = state?.payload;
  const liveOverlay = useMemo(
    () => (editPayload ? editingOverlay(editPayload) : data?.overlay),
    [editPayload, data],
  );
  const artifactId =
    (activeSession ? undefined : linkedWindow?.artifactId) ??
    liveOverlay?.artifactId;
  const regionEditor: TiffRegionEditorSession | undefined =
    canEdit && artifactRef && onEditingChange && onSaveArtifact
      ? {
          active: state !== null,
          canEdit: Boolean(data && data.url === url),
          state,
          dispatch: dispatchEdit,
          onStartEdit: () => onEditingChange(true),
          renderControls: ({ inModal, shortcutsActive }) =>
            state && (
              <EditControls
                state={state}
                dispatch={dispatchEdit}
                inModal={inModal}
                shortcutsActive={shortcutsActive}
                saving={activeSession?.kind === "saving"}
                error={
                  activeSession?.kind === "editing" ? activeSession.error : null
                }
                onSave={() =>
                  dispatch({ type: "save", workspaceId, artifact: artifactRef })
                }
                onClose={() => onEditingChange(false)}
              />
            ),
        }
      : undefined;
  if (!artifactId) {
    if (url === null) return placeholder;
    return (
      <p role="status">
        {error ? "Text overlay unavailable." : "Loading text regions…"}
      </p>
    );
  }
  let outdatedNotice: string | undefined;
  if (data && data.url !== url) {
    if (url === null) outdatedNotice = "Regions hidden until the next run.";
    else if (error) outdatedNotice = "Text overlay unavailable.";
    else outdatedNotice = "Loading text regions…";
  }
  return (
    <div {...viewportProps} style={{ height }}>
      {parsed && !parsed.ok && <p role="alert">{parsed.reason}</p>}
      <TiffArtifactView
        workspaceId={workspaceId}
        artifactId={artifactId}
        name={recognized ? "Recognized text" : "Detected text"}
        overlay={
          liveOverlay?.artifactId === artifactId ? liveOverlay : undefined
        }
        outdatedNotice={outdatedNotice}
        selection={activeSession ? undefined : linkedWindow?.selection}
        regionEditor={regionEditor}
        onSize={onSize}
      />
    </div>
  );
}
