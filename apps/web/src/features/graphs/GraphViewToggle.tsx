"use client";

import * as React from "react";
import { Clock3, Workflow } from "lucide-react";
import {
  SegmentedControl,
  type SegmentedOption,
} from "@/components/ui/segmented-control";
import { GRAPH_BROWSER_VIEWS, type GraphBrowserView } from "./browser-filters";

/**
 * Names the group for assistive tech. The graph browsers are addressed through
 * this name in their tests and in `e2e/graph-browser-filters.spec.ts`, so it
 * lives here rather than at each call site.
 */
export const GRAPH_VIEW_ARIA_LABEL = "Graph views";

/** One entry per view the address contract allows: a missing label is a type error. */
const VIEW_LABELS: Record<
  GraphBrowserView,
  { readonly text: string; readonly icon: React.ReactElement }
> = {
  recent: { text: "Recent", icon: <Clock3 size={14} aria-hidden="true" /> },
  all: { text: "All", icon: <Workflow size={14} aria-hidden="true" /> },
};

const GRAPH_VIEW_OPTIONS: readonly SegmentedOption<GraphBrowserView>[] =
  GRAPH_BROWSER_VIEWS.map((view) => ({
    value: view,
    label: (
      <>
        {VIEW_LABELS[view].icon}
        {VIEW_LABELS[view].text}
      </>
    ),
  }));

export type GraphViewToggleProps = {
  value: GraphBrowserView;
  onValueChange: (value: GraphBrowserView) => void;
};

/**
 * The Recent/All choice, so both graph browsers draw one shared radio group
 * instead of keeping local copies of the same two tabs.
 */
export function GraphViewToggle({
  value,
  onValueChange,
}: GraphViewToggleProps) {
  return (
    <SegmentedControl
      aria-label={GRAPH_VIEW_ARIA_LABEL}
      value={value}
      options={GRAPH_VIEW_OPTIONS}
      onValueChange={onValueChange}
    />
  );
}
