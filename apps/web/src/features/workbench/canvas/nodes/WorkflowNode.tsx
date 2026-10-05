"use client";

import type { NodeProps } from "@xyflow/react";

import {
  IncompatibleWorkflowNodeCard,
  SupportedWorkflowNodeCard,
} from "./workflow/cards";
import type { WorkflowNode } from "./workflow/node-type";
import { CollectionCard } from "./CollectionCard";
import { isCollectionSpec } from "../../model/collection";

function WorkflowNodeCard(props: NodeProps<WorkflowNode>) {
  if (props.data.compatibility.status === "supported") {
    // A collection reads as the artifacts it gathers, not as an operator.
    if (isCollectionSpec(props.data.spec)) {
      return (
        <CollectionCard
          id={props.id}
          data={props.data}
          selected={props.selected}
          dragging={props.dragging}
        />
      );
    }
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
