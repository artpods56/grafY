import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";
import { expect, it } from "vitest";
import AgentCard from "./AgentCard";
it("shows configuration only to editors and explains unsaved conversations", () => {
  const data = {
    agent: {
      id: "a",
      name: "Historian",
      instructions: "",
      width: 360,
      height: 480,
    },
    scope: null,
    canEdit: false,
    canSend: false,
    configure: () => {},
    remove: () => {},
  };
  const render = (canEdit: boolean) =>
    renderToStaticMarkup(
      <ReactFlowProvider>
        <AgentCard
          id="a"
          data={{ ...data, canEdit }}
          type="grafyAgent"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable={false}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
          selectable
          draggable={canEdit}
          deletable={canEdit}
        />
      </ReactFlowProvider>,
    );
  expect(render(false)).not.toContain("Configure");
  expect(render(true)).toContain("Configure");
  expect(render(false)).toContain("Save the Project to start a conversation.");
});
