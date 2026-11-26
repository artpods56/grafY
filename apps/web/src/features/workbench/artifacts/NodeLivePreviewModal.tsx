"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Radio } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { API_BASE } from "@/lib/api/client";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { WorkbenchModal } from "../authoring/WorkbenchModal";
import {
  nodeLivePreviewInitialState,
  nodeLivePreviewReducer,
  type NodePreviewFrame,
} from "./node-live-preview-reducer";

const styles = stylex.create({
  shell: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.space3,
    height: "100%",
    minHeight: 0,
  },
  toolbar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space3,
    flexWrap: "wrap",
  },
  statusGroup: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    minWidth: 0,
  },
  statusBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: tokens.space1,
    paddingBlock: 2,
    paddingInline: tokens.space2,
    borderRadius: 999,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  controls: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    flexWrap: "wrap",
  },
  frameStrip: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space1,
    overflowX: "auto",
    paddingBottom: 2,
    flexShrink: 0,
  },
  framePill: {
    flexShrink: 0,
    paddingBlock: 4,
    paddingInline: tokens.space2,
    borderRadius: tokens.radiusSm,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  framePillActive: {
    borderColor: tokens.colorTextEmphasis,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorTextEmphasis,
    fontWeight: 600,
  },
  viewport: {
    flex: 1,
    minHeight: 0,
    overflow: "auto",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorBg,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: tokens.space3,
  },
  viewportActual: {
    alignItems: "flex-start",
    justifyContent: "flex-start",
  },
  imageFit: {
    maxWidth: "100%",
    maxHeight: "100%",
    objectFit: "contain",
    display: "block",
    borderRadius: tokens.radiusSm,
    boxShadow: tokens.shadowNode,
  },
  imageActual: {
    display: "block",
    maxWidth: "none",
    maxHeight: "none",
    borderRadius: tokens.radiusSm,
    boxShadow: tokens.shadowNode,
  },
  textPayload: {
    width: "100%",
    height: "100%",
    margin: 0,
    padding: tokens.space3,
    overflow: "auto",
    fontFamily: "var(--font-mono, ui-monospace, monospace)",
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.5,
    color: tokens.colorText,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    alignSelf: "stretch",
  },
  emptyState: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: tokens.space2,
    textAlign: "center",
    maxWidth: 420,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  footer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space3,
    flexWrap: "wrap",
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
  },
  footerLabel: {
    color: tokens.colorTextEmphasis,
    fontWeight: 500,
  },
});

export interface NodeLivePreviewTarget {
  readonly nodeId: string;
  readonly nodeTitle: string;
  readonly subtitle?: string;
}

export interface NodeLivePreviewModalProps {
  readonly open: boolean;
  readonly onOpenChange: (open: boolean) => void;
  readonly workspaceId: string;
  readonly projectId: string | null;
  readonly graphId: string | null;
  readonly target: NodeLivePreviewTarget | null;
}

function formatTextPayload(frame: NodePreviewFrame): string {
  const raw = frame.text ?? "";
  if (frame.content_type === "application/json") {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }
  return raw;
}

function isPreviewFrame(value: unknown): value is NodePreviewFrame {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.sequence === "number" &&
    typeof record.computation_id === "string" &&
    typeof record.label === "string" &&
    typeof record.content_type === "string"
  );
}

export function NodeLivePreviewModal({
  open,
  onOpenChange,
  workspaceId,
  projectId,
  graphId,
  target,
}: NodeLivePreviewModalProps) {
  const streamUrl =
    open && projectId && graphId && target
      ? `${API_BASE}/v1/workspaces/${encodeURIComponent(workspaceId)}/projects/${encodeURIComponent(projectId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(target.nodeId)}/preview-stream`
      : null;

  const streamKey = streamUrl ?? "closed";
  const [state, dispatch] = React.useReducer(
    nodeLivePreviewReducer,
    streamKey,
    nodeLivePreviewInitialState,
  );

  React.useEffect(() => {
    dispatch({ type: "reset", streamKey });
    if (!streamUrl) return;

    const source = new EventSource(streamUrl);
    const onReady = () => {
      dispatch({ type: "connected", streamKey });
    };
    const onFrame = (event: MessageEvent<string>) => {
      try {
        const parsed: unknown = JSON.parse(event.data);
        if (isPreviewFrame(parsed)) {
          dispatch({ type: "frame", streamKey, frame: parsed });
        }
      } catch {
        // Ignore malformed preview frames.
      }
    };
    source.onopen = onReady;
    source.addEventListener("ready", onReady);
    source.addEventListener("frame", onFrame as EventListener);
    source.onerror = () => {
      dispatch({ type: "reconnecting", streamKey });
    };

    return () => {
      source.removeEventListener("ready", onReady);
      source.removeEventListener("frame", onFrame as EventListener);
      source.close();
    };
  }, [streamKey, streamUrl]);

  const currentFrame = state.frames[state.selectedIndex] ?? null;
  const isImage = currentFrame?.data_url != null;

  const statusText =
    state.status === "live"
      ? "Live"
      : state.status === "reconnecting"
        ? "Reconnecting…"
        : "Connecting…";

  return (
    <WorkbenchModal
      open={open}
      onOpenChange={onOpenChange}
      size="viewport"
      bodyLayout="fill"
      title={target ? `${target.nodeTitle} — live preview` : "Live preview"}
      description={target?.subtitle}
    >
      <div {...stylex.props(styles.shell)}>
        {!projectId || !graphId ? (
          <Notice tone="neutral">
            Save or open a Project first — live node preview streams frames from
            a saved Project run.
          </Notice>
        ) : (
          <>
            <div {...stylex.props(styles.toolbar)}>
              <div {...stylex.props(styles.statusGroup)}>
                <span {...stylex.props(styles.statusBadge)}>
                  <Radio size={12} aria-hidden="true" />
                  {statusText}
                </span>
                {state.frames.length > 0 ? (
                  <span>
                    Frame {state.selectedIndex + 1} of {state.frames.length}
                  </span>
                ) : null}
              </div>

              <div {...stylex.props(styles.controls)}>
                {state.frames.length > 1 ? (
                  <Button
                    type="button"
                    size="sm"
                    variant={state.followLatest ? "primary" : "secondary"}
                    onClick={() => dispatch({ type: "toggle_follow" })}
                  >
                    {state.followLatest ? "Following latest" : "Follow latest"}
                  </Button>
                ) : null}
                {isImage ? (
                  <SegmentedControl
                    aria-label="Image zoom"
                    size="sm"
                    value={state.zoom}
                    onValueChange={(value) =>
                      dispatch({
                        type: "set_zoom",
                        zoom: value,
                      })
                    }
                    options={[
                      { value: "fit" as const, label: "Fit" },
                      { value: "actual" as const, label: "100%" },
                    ]}
                  />
                ) : null}
              </div>
            </div>

            {state.frames.length > 1 ? (
              <div
                {...stylex.props(styles.frameStrip)}
                role="tablist"
                aria-label="Preview frames"
              >
                {state.frames.map((frame, index) => (
                  <button
                    key={`${frame.computation_id}:${frame.sequence}`}
                    type="button"
                    role="tab"
                    aria-selected={index === state.selectedIndex}
                    {...stylex.props(
                      styles.framePill,
                      index === state.selectedIndex && styles.framePillActive,
                    )}
                    onClick={() => dispatch({ type: "select_frame", index })}
                  >
                    {frame.label}
                  </button>
                ))}
              </div>
            ) : null}

            <div
              {...stylex.props(
                styles.viewport,
                isImage && state.zoom === "actual" && styles.viewportActual,
              )}
            >
              {currentFrame === null ? (
                <div {...stylex.props(styles.emptyState)}>
                  <strong>Waiting for live frames</strong>
                  <span>
                    Run this node to watch what it processes in real time. The
                    most recent frames stay buffered in memory right after a run
                    finishes.
                  </span>
                </div>
              ) : currentFrame.data_url ? (
                <img /* eslint-disable-line @next/next/no-img-element -- streamed data URL frame */
                  src={currentFrame.data_url}
                  alt={currentFrame.label}
                  {...stylex.props(
                    state.zoom === "fit" ? styles.imageFit : styles.imageActual,
                  )}
                />
              ) : (
                <pre {...stylex.props(styles.textPayload)}>
                  {formatTextPayload(currentFrame)}
                </pre>
              )}
            </div>

            {currentFrame ? (
              <div {...stylex.props(styles.footer)}>
                <span {...stylex.props(styles.footerLabel)}>
                  {currentFrame.label}
                </span>
                <span>
                  {[currentFrame.detail, currentFrame.content_type]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </div>
            ) : null}
          </>
        )}
      </div>
    </WorkbenchModal>
  );
}
