"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import { Surface } from "@/components/ui/surface";
import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * The calm first step on a canvas that has nothing on it yet.
 *
 * It sits in a layer that ignores the pointer, so this panel turns the pointer
 * back on for itself and a drop on it stays here.
 */
export function EmptyCanvasStarter({
  status,
  samplePending = false,
  onFiles,
  onSample,
  onBrowseSteps,
}: {
  status: string | null;
  samplePending?: boolean;
  onFiles: (files: readonly File[]) => void;
  onSample: () => void;
  onBrowseSteps: () => void;
}) {
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const busy = status !== null || samplePending;

  const takeFiles = (files: readonly File[]) => {
    if (busy || files.length === 0) return;
    onFiles(files);
  };

  return (
    <Surface tone="floating" padding="md" shape="lg" xstyle={styles.panel}>
      <button
        type="button"
        disabled={busy}
        {...stylex.props(styles.drop)}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(event) => {
          if (!carriesFiles(event.dataTransfer)) return;
          event.preventDefault();
          event.stopPropagation();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={(event) => {
          const files = Array.from(event.dataTransfer.files);
          if (files.length === 0) return;
          event.preventDefault();
          event.stopPropagation();
          takeFiles(files);
        }}
      >
        Drop a scanned page, PDF, or spreadsheet here
      </button>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        tabIndex={-1}
        onChange={(event) => {
          const picked = Array.from(event.target.files ?? []);
          event.target.value = "";
          takeFiles(picked);
        }}
      />
      <div {...stylex.props(styles.actions)}>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={onSample}
        >
          Try a sample historical page
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onBrowseSteps}>
          Browse steps
        </Button>
      </div>
      {status ? (
        <p role="status" {...stylex.props(styles.status)}>
          {status}
        </p>
      ) : null}
    </Surface>
  );
}

function carriesFiles(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types).includes("Files");
}

const styles = stylex.create({
  panel: {
    pointerEvents: "auto",
    width: "min(420px, calc(100% - 48px))",
    display: "grid",
    justifyItems: "center",
    gap: "12px",
  },
  drop: {
    width: "100%",
    minHeight: "88px",
    padding: "16px",
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: {
      default: tokens.colorBorder,
      ":hover:not(:disabled)": tokens.colorAccentBorder,
    },
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default:
        "light-dark(color-mix(in srgb, white 72%, transparent), color-mix(in srgb, white 8%, transparent))",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.4,
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: "8px",
  },
  status: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
});
