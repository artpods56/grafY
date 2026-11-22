// @vitest-environment jsdom

import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { CellCanvas } from "@/features/workbench/cell-canvas/CellCanvas";
import { cellGraphFromAuthoredDocument } from "@/features/workbench/cell-canvas/cell-document-adapter";
import { askAModelRegistry } from "../../fixtures/ask-a-model-registry";
import { askAModelDocument } from "../../fixtures/graphs/ask-a-model";
import { inspectCards } from "./canvas-inspection";

it("measures the real authored card and locates its ports and tabs", () => {
  const scene = cellGraphFromAuthoredDocument(
    askAModelDocument,
    askAModelRegistry,
  );
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(
    <CellCanvas {...scene} editable={false} />,
  );
  const input = root.querySelector("[data-port-id='messages']");
  if (!input) throw new Error("Ask a model has no Instructions port");
  input.getBoundingClientRect = () => new DOMRect(35, 50, 30, 30);

  const cards = inspectCards(root);
  expect(cards).toHaveLength(1);
  expect(cards[0]).toMatchObject({
    id: "ask-model",
    ports: expect.arrayContaining([
      {
        id: "messages",
        direction: "input",
        centre: { x: 50, y: 65 },
        rect: { x: 35, y: 50, width: 30, height: 30 },
      },
      expect.objectContaining({ id: "completion", direction: "output" }),
    ]),
    tabs: expect.arrayContaining([
      expect.objectContaining({ id: "messages", row: "2" }),
    ]),
  });
});
