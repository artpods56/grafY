"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowDownToLine, ArrowUpFromLine } from "lucide-react";

import { artifactTitleFor } from "../CatalogNodePreview";
import { artifactTypeColor } from "../../canvas/nodes.css";
import {
  acceptedPortShapes,
  portArtifactType,
  portArtifactTypeVariable,
  portHasInstancePlugs,
} from "../../canvas/types";
import type { NodeRegistry, Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { styles as s } from "./styles";

export interface PortListProps {
  direction: "input" | "output";
  ports: readonly Port[];
  registry: NodeRegistry;
}

export function PortList({ direction, ports, registry }: PortListProps) {
  const input = direction === "input";
  return (
    <div>
      <h4 {...stylex.props(s.portColumnHeading)}>
        {input ? <ArrowDownToLine size={12} /> : <ArrowUpFromLine size={12} />}
        {input ? "Inputs" : "Outputs"} · {ports.length}
      </h4>
      {ports.length ? (
        <div {...stylex.props(s.portList)}>
          {ports.map((port) => {
            const artifactType = portArtifactType(port);
            const variable = portArtifactTypeVariable(port);
            const contract = artifactType
              ? `${artifactType.id}@${artifactType.schema_version}`
              : (variable ?? "generic");
            const acceptedShapeRule = acceptedPortShapes(port)
              .map((shape) => (shape === "many" ? "sequence" : "single value"))
              .join(" or ");
            const rules = [
              port.required ? "required" : "optional",
              acceptedShapeRule,
              portHasInstancePlugs(port)
                ? "ordered input plugs"
                : port.variadic
                  ? "multiple connections"
                  : null,
            ]
              .filter(Boolean)
              .join(" · ");
            return (
              <div
                key={`${direction}-${port.name}`}
                {...stylex.props(s.portRow)}
              >
                <span
                  aria-hidden="true"
                  {...stylex.props(s.portDot)}
                  style={{
                    backgroundColor: artifactType
                      ? artifactTypeColor(artifactType.id, tokens.colorAccent)
                      : tokens.colorAccent,
                  }}
                />
                <div {...stylex.props(s.portCopy)}>
                  <div {...stylex.props(s.portTitle)}>
                    {port.title ?? port.name}
                  </div>
                  <div {...stylex.props(s.portContract)}>
                    {artifactTitleFor(registry, port)} · {contract}
                  </div>
                  <div {...stylex.props(s.portRules)}>{rules}</div>
                  {port.description ? (
                    <p {...stylex.props(s.portDescription)}>
                      {port.description}
                    </p>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p {...stylex.props(s.compatibilityEmpty)}>
          {input
            ? "No inputs. This node can start a workflow."
            : "No outputs. This node finishes a branch."}
        </p>
      )}
    </div>
  );
}
