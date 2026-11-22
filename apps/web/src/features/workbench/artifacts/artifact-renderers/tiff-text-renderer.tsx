"use client";

import useSWR from "swr";

import { TiffArtifactView, type PixelPolygon } from "../TiffArtifactView";
import {
  readTiffWindow,
  type TiffWindowSelection,
} from "../TiffWindowSelector";
import { record } from "./payload";

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
  const payload: unknown = await response.json();
  const overlay = overlayPayload(payload);
  if (!overlay) throw new Error("Invalid text regions.");
  return overlay;
}

export function TiffTextArtifact({
  url,
  workspaceId,
  height,
  linkedWindow,
  recognized = false,
  onSize,
}: {
  url: string | null;
  workspaceId: string;
  height: number;
  linkedWindow?: { artifactId: string; selection: TiffWindowSelection };
  recognized?: boolean;
  /** The linked scan's pixel size, once its tile pyramid describes it. */
  onSize?: (width: number, height: number) => void;
}) {
  const { data, error } = useSWR(url, fetchOverlay, { keepPreviousData: true });
  const artifactId = linkedWindow?.artifactId ?? data?.artifactId;
  if (!artifactId) {
    return (
      <p role="status">
        {error ? "Text overlay unavailable." : "Loading text regions…"}
      </p>
    );
  }
  return (
    <div style={{ height }}>
      <TiffArtifactView
        workspaceId={workspaceId}
        artifactId={artifactId}
        name={recognized ? "Recognized text" : "Detected text"}
        overlay={data?.artifactId === artifactId ? data : undefined}
        selection={linkedWindow?.selection}
        onSize={onSize}
      />
    </div>
  );
}
