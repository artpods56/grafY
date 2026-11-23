"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";

import type { SavedGraphSummary } from "@/lib/api";
import { railStyles } from "./workspace-rail.stylex";

export function GraphRowMenu({
  graph,
  busy = false,
  onRename,
  onDelete,
}: {
  graph: SavedGraphSummary;
  busy?: boolean;
  onRename: (graph: SavedGraphSummary) => void;
  onDelete: (graph: SavedGraphSummary) => void;
}) {
  const [open, setOpen] = React.useState(false);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className={stylex.props(railStyles.menuTrigger).className}
        disabled={busy}
        aria-label={`Actions for ${graph.name}`}
        title="Graph actions"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
      >
        <MoreHorizontal size={14} aria-hidden="true" />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner
          className={stylex.props(railStyles.accountPositioner).className}
          side="right"
          align="start"
          sideOffset={4}
        >
          <Popover.Popup
            className={stylex.props(railStyles.accountMenu).className}
            data-account-menu=""
          >
            <button
              type="button"
              className={stylex.props(railStyles.accountMenuItem).className}
              onClick={() => {
                setOpen(false);
                onRename(graph);
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              Rename
            </button>
            <button
              type="button"
              className={
                stylex.props(
                  railStyles.accountMenuItem,
                  railStyles.accountMenuItemDanger,
                ).className
              }
              onClick={() => {
                setOpen(false);
                onDelete(graph);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Delete
            </button>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function promptGraphRename(currentName: string): string | null {
  const next = window.prompt("Rename graph", currentName);
  if (next === null) return null;
  const trimmed = next.trim();
  if (!trimmed || trimmed === currentName) return null;
  return trimmed.slice(0, 160);
}
