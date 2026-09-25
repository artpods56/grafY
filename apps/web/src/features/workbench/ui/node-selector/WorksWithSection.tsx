"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Cable } from "lucide-react";

import { portKey } from "../CatalogNodePreview";
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { portScopeLabel } from "./catalog-labels";
import type { CompatibleNode } from "./compatibility";
import { CompatibilityList } from "./CompatibilityList";
import { styles as s } from "./styles";

export interface WorksWithSectionProps {
  ports: readonly Port[];
  activePort: Port;
  matches: readonly CompatibleNode[];
  registry: NodeRegistry;
  onSelectPort: (port: Port) => void;
  onInspect: (spec: NodeSpec) => void;
}

export function WorksWithSection({
  ports,
  activePort,
  matches,
  registry,
  onSelectPort,
  onInspect,
}: WorksWithSectionProps) {
  const receiving = activePort.direction === "input";
  return (
    <section {...stylex.props(s.section)}>
      <div {...stylex.props(s.worksWithHeader)}>
        <Cable size={13} {...stylex.props(s.sectionIcon)} />
        <h3 {...stylex.props(s.worksWithTitle)}>Works with:</h3>
        {ports.length > 1 ? (
          <select
            aria-label="Works with port"
            value={portKey(activePort)}
            {...stylex.props(s.worksWithPort, s.worksWithPortSelect)}
            onChange={(event) => {
              const next = ports.find(
                (port) => portKey(port) === event.currentTarget.value,
              );
              if (next) onSelectPort(next);
            }}
          >
            {ports.map((port) => (
              <option key={portKey(port)} value={portKey(port)}>
                {portScopeLabel(port)}
              </option>
            ))}
          </select>
        ) : (
          <span {...stylex.props(s.worksWithPort)}>
            {portScopeLabel(activePort)}
          </span>
        )}
      </div>
      <CompatibilityList
        matches={matches}
        registry={registry}
        emptyMessage={
          receiving
            ? "No registered node currently provides a compatible output."
            : "No registered node currently accepts this output."
        }
        onInspect={onInspect}
      />
    </section>
  );
}
