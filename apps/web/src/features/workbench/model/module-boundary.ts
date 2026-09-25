import type { WorkflowEdge } from "../canvas/types";
import type { WorkflowNode } from "./execution-plan";

const MODULE_INPUT_OPERATOR_ID = "module.input";
const MODULE_OUTPUT_OPERATOR_ID = "module.output";

export interface ModuleBoundarySummary {
  id: string;
  direction: "input" | "output";
  portName: string | null;
  description: string | null;
  artifactType: string | null;
  connectionCount: number;
}

/**
 * The `module.input` and `module.output` nodes that define a module's public shape,
 * each with the number of live connections the author has wired to it.
 */
export function moduleBoundaries(
  nodes: readonly WorkflowNode[],
  edges: readonly WorkflowEdge[],
): ModuleBoundarySummary[] {
  return nodes.flatMap((node) => {
    const operatorId = node.data.spec.operator_id;
    if (
      operatorId !== MODULE_INPUT_OPERATOR_ID &&
      operatorId !== MODULE_OUTPUT_OPERATOR_ID
    ) {
      return [];
    }
    const direction =
      operatorId === MODULE_INPUT_OPERATOR_ID ? "input" : "output";
    const portName = node.data.config.public_name;
    const description = node.data.config.description;
    const artifactType = node.data.artifactTypeBindings.T;
    const connectionCount = edges.filter(
      (edge) =>
        edge.data?.enabled !== false &&
        (direction === "input"
          ? edge.source === node.id
          : edge.target === node.id),
    ).length;
    return [
      {
        id: node.id,
        direction,
        portName: typeof portName === "string" ? portName : null,
        description: typeof description === "string" ? description : null,
        artifactType: artifactType
          ? `${artifactType.id}@${artifactType.schema_version}`
          : null,
        connectionCount,
      },
    ];
  });
}
