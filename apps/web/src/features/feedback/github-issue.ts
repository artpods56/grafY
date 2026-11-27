import type { FeedbackReport } from "@/lib/api/contract";

/** The repository operators file app feedback in. */
export const FEEDBACK_ISSUE_REPOSITORY = "artpods56/grafY";

const KIND_TITLE = { bug: "Bug", idea: "Idea", other: "Feedback" } as const;
const MAX_TITLE = 80;
const MAX_BODY_MESSAGE = 2000;
const UUID_PATTERN =
  /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** The screen a report came from, without the Workspace slug or record ids. */
export function publicPagePath(pagePath: string): string {
  return pagePath
    .replace(/^\/workspaces\/[^/]+/, "/workspaces/<workspace>")
    .replace(UUID_PATTERN, "<id>");
}

/**
 * A prefilled "new issue" form for one report. The repository is public, so the
 * body carries what the person wrote and which screen it was, never who they are
 * or which Workspace they were in. The operator reads it over before submitting:
 * the message and the element label can still hold research data.
 */
export function githubIssueUrl(report: FeedbackReport): string {
  const firstLine = report.message.split("\n", 1)[0]?.trim() ?? "";
  const title = `${KIND_TITLE[report.kind]}: ${
    firstLine.length > MAX_TITLE
      ? `${firstLine.slice(0, MAX_TITLE - 1)}…`
      : firstLine
  }`;
  const message =
    report.message.length > MAX_BODY_MESSAGE
      ? `${report.message.slice(0, MAX_BODY_MESSAGE)}… (truncated)`
      : report.message;
  const lines = [
    message,
    "",
    "### Where",
    `- Screen: \`${publicPagePath(report.page_path)}\``,
  ];
  const element = report.element;
  if (element) {
    const role = element.role ? ` (${element.role})` : "";
    lines.push(`- Element: ${element.label ?? element.tag}${role}`);
    lines.push(`- Selector: \`${element.selector}\``);
  }
  const client = report.client;
  lines.push(
    `- Viewport: ${client.viewport_width}×${client.viewport_height} @${client.device_pixel_ratio}x, ${client.color_scheme} theme`,
    `- Browser: ${client.user_agent}`,
    "",
    `_From in-app feedback report \`${report.id}\`${
      report.screenshot ? "; the screenshot is in the feedback inbox" : ""
    }._`,
  );
  const params = new URLSearchParams({
    title,
    body: lines.join("\n"),
    labels: "triage",
  });
  return `https://github.com/${FEEDBACK_ISSUE_REPOSITORY}/issues/new?${params.toString()}`;
}
