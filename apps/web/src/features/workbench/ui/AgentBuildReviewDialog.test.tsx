import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <T,>(styles: T) => styles,
  defineVars: <T,>(variables: T) => variables,
  props: () => ({}),
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div>{children}</div> : null,
  DialogBody: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

import { AgentBuildReviewDialog } from "./AgentBuildReviewDialog";

function reviewProps(capabilityApprovalId: string | null = null) {
  return {
    open: true,
    nodeTitle: "Normalize records",
    review: {
      build: {
        id: "build-2",
        capabilities: {
          outbound_http_origins: ["https://api.example.test"],
          secret_refs: ["provider-token"],
          object_store: [{ scope: "read", prefix: "inputs/" }],
          runtime: {
            cpu_millis: 500,
            memory_megabytes: 128,
            wall_time_seconds: 30,
          },
          digest: "a".repeat(64),
        },
      },
      tests: { passed: true, file_count: 2, digest: "b".repeat(64) },
      files: [{
        path: "src/generated_node/main.py",
        kind: "implementation",
        byte_count: 38,
        sha256: "c".repeat(64),
      }],
      changes: [{
        path: "src/generated_node/main.py",
        kind: "implementation",
        change: "modified",
        previous_sha256: "d".repeat(64),
        current_sha256: "c".repeat(64),
        unified_diff: "-return old\n+return normalized",
        diff_truncated: false,
      }],
      previous_release_revision: 1,
    } as never,
    selectedFile: {
      path: "src/generated_node/main.py",
      kind: "implementation",
      byte_count: 38,
      sha256: "c".repeat(64),
      content: "def run():\n    return normalized",
    } as const,
    selectedPath: "src/generated_node/main.py",
    loading: false,
    fileLoading: false,
    error: null,
    pendingAction: null,
    capabilityApprovalId,
    onOpenChange: vi.fn(),
    onSelectFile: vi.fn(),
    onApprove: vi.fn(),
    onPublish: vi.fn(),
  } as const;
}

describe("AgentBuildReviewDialog", () => {
  it("shows verified tests, curated diff, capabilities, and exact digest before approval", () => {
    const html = renderToStaticMarkup(
      <AgentBuildReviewDialog {...reviewProps()} />,
    );

    expect(html).toContain("2 test files passed");
    expect(html).toContain("src/generated_node/main.py");
    expect(html).toContain("return normalized");
    expect(html).toContain("https://api.example.test");
    expect(html).toContain("provider-token");
    expect(html).toContain("a".repeat(64));
    expect(html).toContain("Approve exact capabilities");
    expect(html).not.toContain("Publish node");
  });

  it("offers publication only after the exact approval id exists", () => {
    const html = renderToStaticMarkup(
      <AgentBuildReviewDialog {...reviewProps("approval-exact")} />,
    );

    expect(html).toContain("Publish node");
    expect(html).not.toContain("Approve exact capabilities");
  });
});
