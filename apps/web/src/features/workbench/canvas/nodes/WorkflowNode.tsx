"use client";

import type { NodeProps } from "@xyflow/react";

import {
  IncompatibleWorkflowNodeCard,
  SupportedWorkflowNodeCard,
} from "./workflow/cards";
import type { WorkflowNode } from "./workflow/node-type";

function WorkflowNodeCard(props: NodeProps<WorkflowNode>) {
  if (props.data.compatibility.status === "supported") {
    return <SupportedWorkflowNodeCard {...props} />;
  }
  return (
    <IncompatibleWorkflowNodeCard
      id={props.id}
      data={props.data}
      selected={props.selected}
      dragging={props.dragging}
      compatibility={props.data.compatibility}
    />
  );
}

export default WorkflowNodeCard;
