import type { Node } from "@xyflow/react";

import { WORKFLOW_NODE_TYPE, type WorkflowNodeData } from "../../types";

export type WorkflowNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;
