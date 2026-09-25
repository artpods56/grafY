"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import type { NodeRegistry, NodeSpec } from "@/lib/api";
import { nodeKey, pluginFor, type CompatibleNode } from "./compatibility";
import { styles as s } from "./styles";

export interface CompatibilityListProps {
  title?: string;
  matches: readonly CompatibleNode[];
  registry: NodeRegistry;
  emptyMessage: string;
  onInspect: (spec: NodeSpec) => void;
}

export function CompatibilityList({
  title,
  matches,
  registry,
  emptyMessage,
  onInspect,
}: CompatibilityListProps) {
  return (
    <div>
      {title ? (
        <h4 {...stylex.props(s.compatibilityHeading)}>{title}</h4>
      ) : null}
      {matches.length ? (
        <div {...stylex.props(s.compatibilityList)}>
          {matches.map((match) => (
            <button
              key={nodeKey(match.spec)}
              type="button"
              aria-label={`Inspect ${match.spec.title}`}
              {...stylex.props(s.compatibilityItem)}
              onClick={() => onInspect(match.spec)}
            >
              <span {...stylex.props(s.compatibilityName)}>
                {match.spec.title}
              </span>
              <span {...stylex.props(s.compatibilityMeta)}>
                {pluginFor(registry, match.spec.plugin_slug).title} ·{" "}
                {match.routeSummary}
                {match.additionalRouteCount > 0
                  ? ` · +${match.additionalRouteCount} route${match.additionalRouteCount === 1 ? "" : "s"}`
                  : ""}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p {...stylex.props(s.compatibilityEmpty)}>{emptyMessage}</p>
      )}
    </div>
  );
}
