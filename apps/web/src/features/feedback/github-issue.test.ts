import { describe, expect, it } from "vitest";

import type { FeedbackReport } from "@/lib/api/contract";

import { githubIssueUrl, publicPagePath } from "./github-issue";

const report = {
  id: "9b2e7c1a-1111-4222-8333-444455556666",
  created_at: "2026-11-27T10:00:00Z",
  kind: "bug",
  message: "The run button does nothing\nSecond line",
  page_path:
    "/workspaces/history-lab/projects/0f8fad5b-d9cb-469f-a165-70867728950e",
  status: "open",
  resolved_at: null,
  github_issue_url: null,
  reporter: { id: "u1", email: "person@example.test", display_name: "Person" },
  workspace: { id: "w1", slug: "history-lab", name: "History lab" },
  element: {
    tag: "button",
    selector: "main > button",
    label: "Run",
    role: "button",
    test_id: null,
    canvas_item_id: "card-1",
    text: "Run",
    rect: { x: 0, y: 0, width: 10, height: 10 },
  },
  client: {
    viewport_width: 1280,
    viewport_height: 800,
    device_pixel_ratio: 2,
    user_agent: "Firefox",
    color_scheme: "light",
  },
  screenshot: { content_type: "image/png", byte_size: 10 },
} as unknown as FeedbackReport;

describe("githubIssueUrl", () => {
  it("prefills a new issue in the feedback repository", () => {
    const url = new URL(githubIssueUrl(report));
    expect(url.origin + url.pathname).toBe(
      "https://github.com/artpods56/grafY/issues/new",
    );
    expect(url.searchParams.get("title")).toBe(
      "Bug: The run button does nothing",
    );
    expect(url.searchParams.get("labels")).toBe("triage");
    const body = url.searchParams.get("body")!;
    expect(body).toContain("Second line");
    expect(body).toContain("- Screen: `/workspaces/<workspace>/projects/<id>`");
    expect(body).toContain("- Element: Run (button)");
  });

  it("leaves out who sent it and which Workspace it came from", () => {
    const body = new URL(githubIssueUrl(report)).searchParams.get("body")!;
    expect(body).not.toContain("person@example.test");
    expect(body).not.toContain("Person");
    expect(body).not.toContain("history-lab");
    expect(body).not.toContain("History lab");
  });
});

describe("publicPagePath", () => {
  it("hides the Workspace slug and record ids", () => {
    expect(publicPagePath("/workspaces/lab/settings")).toBe(
      "/workspaces/<workspace>/settings",
    );
    expect(publicPagePath("/")).toBe("/");
  });
});
