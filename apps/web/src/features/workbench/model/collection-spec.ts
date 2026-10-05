import type { NodeSpec } from "@/lib/api";
import {
  workflowNodeIsSupported,
  type WorkflowNodeData,
} from "../canvas/types";

/**
 * What marks a node as a collection. Kept apart from `collection`, which builds
 * the graph commands, because the execution plan and the node catalog only need
 * to recognise one.
 */
export const COLLECTION_OPERATOR_ID = "sequence.collect";
export const COLLECTION_PORT = "items";

export function isCollectionSpec(
  spec: Pick<NodeSpec, "operator_id"> | null | undefined,
): boolean {
  return spec?.operator_id === COLLECTION_OPERATOR_ID;
}

export function isCollectionNode(node: { data: WorkflowNodeData }): boolean {
  return workflowNodeIsSupported(node.data) && isCollectionSpec(node.data.spec);
}
