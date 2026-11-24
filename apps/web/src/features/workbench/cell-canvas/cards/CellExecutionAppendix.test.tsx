// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { computeOperatorCardLayout } from "../cell-card-geometry";
import type {
  CellExecutionAppendixOutput,
  CellExecutionAppendixSpec,
  OperatorCardSurfaceData,
} from "../cell-contracts";
import type { CellCardModel } from "../cell-model";
import {
  CellOperatorCard,
  type CellOperatorCardProps,
} from "./CellOperatorCard";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const SAMPLE_OUTPUTS: readonly CellExecutionAppendixOutput[] = [
  {
    port: "markdown",
    label: "Transcription",
    count: 1,
    kind: "single",
    typeLabel: "Markdown",
    typeKey: "text.markdown@1",
    toneColor: "light-dark(#b46735, #e88a50)",
    artifactIds: ["m1"],
  },
  {
    port: "blocks",
    label: "Text blocks",
    count: 2,
    kind: "sequence",
    typeLabel: "Document OCR blocks",
    typeKey: "ocr.document_result@1",
    toneColor: "light-dark(#7b63c9, #9a7cf2)",
    artifactIds: ["b1", "b2"],
  },
  {
    port: "regions",
    label: "Boxes on the page",
    count: 3,
    kind: "sequence",
    typeLabel: "Page regions",
    typeKey: "ocr.tiff_text_regions@1",
    toneColor: "light-dark(#2a9d7c, #43c59e)",
    artifactIds: ["r1", "r2", "r3"],
  },
];

function mountAppendix(
  appendix: CellExecutionAppendixSpec,
  props: Partial<CellOperatorCardProps> = {},
) {
  const surface: OperatorCardSurfaceData = {
    kind: "operator",
    statusLabel: appendix.kind === "error" ? "Error" : "Fresh",
    appendix,
  };
  const baseCard: CellCardModel = {
    id: "ocr-1",
    title: "Document OCR",
    subtitle: "ocr.read_document",
    kind: "operator",
    status: appendix.kind === "error" ? "error" : "done",
    col: 0,
    row: 0,
    widthCells: 12,
    heightCells: 4,
    ports: [
      {
        id: "markdown",
        name: "Transcription",
        direction: "output",
        rowOffset: 2,
        artifactTypeId: "text.markdown",
        shape: "one",
      },
    ],
  };
  const card: CellCardModel = {
    ...baseCard,
    heightCells: computeOperatorCardLayout(baseCard, surface).totalHeightCells,
  };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <CellOperatorCard
        card={card}
        surface={surface}
        selected={false}
        dragging={false}
        {...props}
      />,
    );
  });
  return { container, card };
}

describe("CellExecutionAppendix interactions", () => {
  it("toggles expansion and fires onToggleAppendix with the card id", () => {
    const onToggleAppendix = vi.fn();
    const { container } = mountAppendix(
      {
        kind: "output",
        title: "Outputs",
        kindBadge: "Output",
        heightCells: 5,
        collapsed: true,
        summaryText: "3 outputs · 6 items",
        itemCount: 6,
        outputs: SAMPLE_OUTPUTS,
      },
      { onToggleAppendix },
    );

    const toggle = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Expand outputs"]',
    );
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    React.act(() => {
      toggle?.click();
    });
    expect(onToggleAppendix).toHaveBeenCalledWith("ocr-1");
  });

  it("caps the header color dot cluster at 4 dots and invokes onOutputPortClick when wired", () => {
    const onOutputPortClick = vi.fn();
    const fiveOutputs: CellExecutionAppendixOutput[] = [
      ...SAMPLE_OUTPUTS,
      {
        port: "table",
        label: "Extracted table",
        count: 1,
        kind: "single",
        typeLabel: "Table",
        typeKey: "table.data@1",
        toneColor: "light-dark(#237f8d, #3db0bd)",
        artifactIds: ["t1"],
      },
      {
        port: "trace",
        label: "Trace",
        count: 1,
        kind: "single",
        typeLabel: "Trace",
        typeKey: "ocr.request_trace@1",
        toneColor: "light-dark(#c9920f, #fbbf24)",
        artifactIds: ["tr1"],
      },
    ];
    const { container } = mountAppendix(
      {
        kind: "output",
        title: "Outputs",
        kindBadge: "Output",
        heightCells: 7,
        collapsed: false,
        summaryText: "5 outputs · 8 items",
        itemCount: 8,
        outputs: fiveOutputs,
      },
      { onOutputPortClick },
    );

    const clusterDots = container.querySelectorAll(
      '[data-appendix-dot-cluster="true"] > span',
    );
    expect(clusterDots).toHaveLength(4);

    const action = container.querySelector<HTMLButtonElement>(
      '[data-appendix-output-action="blocks"]',
    );
    expect(action).not.toBeNull();
    React.act(() => {
      action?.click();
    });
    expect(onOutputPortClick).toHaveBeenCalledWith("ocr-1", fiveOutputs[1]);
  });

  it("omits interactive row buttons when onOutputPortClick is not provided", () => {
    const { container } = mountAppendix({
      kind: "output",
      title: "Outputs",
      kindBadge: "Output",
      heightCells: 5,
      collapsed: false,
      summaryText: "3 outputs · 6 items",
      itemCount: 6,
      outputs: SAMPLE_OUTPUTS,
    });

    expect(container.querySelector("[data-appendix-output-action]")).toBeNull();
    expect(container.querySelectorAll("[data-appendix-output]")).toHaveLength(
      3,
    );
  });

  it("copies the full error message on click and confirms with copied state", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    const { container } = mountAppendix({
      kind: "error",
      title: "Run failed",
      kindBadge: "Error",
      heightCells: 4,
      collapsed: false,
      summaryText: "401 Unauthorized from OCR provider",
      errorText: "401 Unauthorized from OCR provider",
    });

    const copyButton = container.querySelector<HTMLButtonElement>(
      '[data-appendix-copy-error="true"]',
    );
    expect(copyButton?.getAttribute("aria-label")).toBe("Copy error");

    await React.act(async () => {
      copyButton?.click();
      await Promise.resolve();
    });

    expect(writeText).toHaveBeenCalledWith(
      "401 Unauthorized from OCR provider",
    );
    expect(
      container
        .querySelector('[data-appendix-copy-error="true"]')
        ?.getAttribute("aria-label"),
    ).toBe("Error copied");

    React.act(() => {
      vi.advanceTimersByTime(1700);
    });
    expect(
      container
        .querySelector('[data-appendix-copy-error="true"]')
        ?.getAttribute("aria-label"),
    ).toBe("Copy error");
  });
});
