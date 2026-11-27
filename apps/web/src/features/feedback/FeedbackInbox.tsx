"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ChevronDown,
  CircleCheck,
  ExternalLink,
  RotateCcw,
  Trash2,
  Unlink,
} from "lucide-react";
import useSWRInfinite from "swr/infinite";

import { Button, ButtonLink } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { graphAgeLabel } from "@/features/workspaces/WorkspaceGraphPanel";
import { ApiError } from "@/lib/api/client";
import type {
  FeedbackKind,
  FeedbackReport,
  FeedbackReportList,
  FeedbackReportUpdate,
  FeedbackStatus,
} from "@/lib/api/contract";
import {
  deleteFeedbackReport,
  feedbackReportsPath,
  feedbackScreenshotUrl,
  updateFeedbackReport,
} from "@/lib/api/feedback";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { githubIssueUrl } from "./github-issue";

const PAGE_SIZE = 25;

type Filter = FeedbackStatus | "all";

const FILTER_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
] as const satisfies readonly { value: Filter; label: string }[];

const KIND_LABEL: Record<FeedbackKind, string> = {
  bug: "Problem",
  idea: "Idea",
  other: "Other",
};

const s = stylex.create({
  root: { display: "grid", gap: tokens.space4, maxWidth: "960px" },
  toolbar: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space3,
  },
  filter: { minWidth: "260px" },
  meta: { color: tokens.colorMuted, fontSize: tokens.fontSizeSm },
  list: { display: "grid", gap: tokens.space2 },
  row: {
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurface,
    overflow: "hidden",
  },
  summary: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: tokens.space3,
    width: "100%",
    paddingBlock: tokens.space3,
    paddingInline: tokens.space4,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorText,
    textAlign: "left",
    cursor: "pointer",
    font: "inherit",
    ":hover": { backgroundColor: tokens.colorHover },
  },
  summaryCopy: { display: "grid", gap: "4px", minWidth: 0 },
  headline: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    minWidth: 0,
  },
  kind: {
    flexShrink: 0,
    paddingBlock: "1px",
    paddingInline: "6px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  kindBug: {
    backgroundColor: tokens.colorWarningSoft,
    color: tokens.colorText,
  },
  message: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
  },
  byline: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  trailing: { display: "flex", alignItems: "center", gap: tokens.space2 },
  resolvedMark: { color: tokens.colorSuccess, flexShrink: 0 },
  thumb: {
    width: "72px",
    height: "48px",
    objectFit: "cover",
    borderRadius: tokens.radiusSm,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceSunken,
    display: { default: "block", "@media (max-width: 620px)": "none" },
  },
  chevron: {
    color: tokens.colorSubtle,
    transitionProperty: "transform",
    transitionDuration: "120ms",
  },
  chevronOpen: { transform: "rotate(180deg)" },
  details: {
    display: "grid",
    gap: tokens.space3,
    paddingBlock: tokens.space3,
    paddingInline: tokens.space4,
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  fullMessage: {
    margin: 0,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.5,
  },
  facts: {
    display: "grid",
    gridTemplateColumns: "max-content minmax(0, 1fr)",
    columnGap: tokens.space3,
    rowGap: "6px",
    margin: 0,
    fontSize: tokens.fontSizeSm,
  },
  factName: { color: tokens.colorMuted },
  factValue: { margin: 0, minWidth: 0, overflowWrap: "anywhere" },
  mono: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
  },
  shot: {
    display: "block",
    maxWidth: "100%",
    maxHeight: "420px",
    borderRadius: tokens.radiusMd,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-end",
    gap: tokens.space2,
  },
  linkForm: {
    display: "flex",
    alignItems: "flex-end",
    gap: tokens.space2,
    flexGrow: 1,
    minWidth: "260px",
  },
  linkField: { flexGrow: 1 },
  empty: {
    paddingBlock: tokens.space6,
    textAlign: "center",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
  more: { justifySelf: "center" },
});

function reporterName(report: FeedbackReport): string {
  if (!report.reporter) return "Deleted user";
  return (
    report.reporter.display_name || report.reporter.email || "Unnamed user"
  );
}

function FeedbackReportRow({
  report,
  onChanged,
}: {
  report: FeedbackReport;
  onChanged: () => Promise<unknown>;
}) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [failure, setFailure] = React.useState<string | null>(null);
  const [issueUrl, setIssueUrl] = React.useState("");
  const detailsId = React.useId();

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setFailure(null);
    try {
      await action();
      await onChanged();
    } catch (error) {
      setFailure(
        error instanceof ApiError && error.status === 422
          ? "That is not a GitHub issue link."
          : "The report could not be updated. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  const update = (body: FeedbackReportUpdate) =>
    act(() => updateFeedbackReport(report.id, body));

  const byline = [
    reporterName(report),
    report.workspace?.name,
    report.page_path,
    graphAgeLabel(report.created_at),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <article {...stylex.props(s.row)}>
      <button
        type="button"
        {...stylex.props(s.summary)}
        aria-expanded={open}
        aria-controls={detailsId}
        onClick={() => setOpen((value) => !value)}
      >
        <span {...stylex.props(s.summaryCopy)}>
          <span {...stylex.props(s.headline)}>
            <span {...stylex.props(s.kind, report.kind === "bug" && s.kindBug)}>
              {KIND_LABEL[report.kind]}
            </span>
            {report.status === "resolved" ? (
              <CircleCheck
                size={14}
                aria-label="Resolved"
                {...stylex.props(s.resolvedMark)}
              />
            ) : null}
            <span {...stylex.props(s.message)}>{report.message}</span>
          </span>
          <span {...stylex.props(s.byline)}>{byline}</span>
        </span>
        <span {...stylex.props(s.trailing)}>
          {report.screenshot ? (
            <img /* eslint-disable-line @next/next/no-img-element -- authenticated screenshot */
              src={feedbackScreenshotUrl(report.id)}
              alt=""
              loading="lazy"
              {...stylex.props(s.thumb)}
            />
          ) : null}
          <ChevronDown
            size={16}
            aria-hidden="true"
            {...stylex.props(s.chevron, open && s.chevronOpen)}
          />
        </span>
      </button>

      {open ? (
        <div id={detailsId} {...stylex.props(s.details)}>
          <p {...stylex.props(s.fullMessage)}>{report.message}</p>
          <dl {...stylex.props(s.facts)}>
            <dt {...stylex.props(s.factName)}>From</dt>
            <dd {...stylex.props(s.factValue)}>
              {reporterName(report)}
              {report.reporter?.email ? ` <${report.reporter.email}>` : ""}
            </dd>
            {report.workspace ? (
              <>
                <dt {...stylex.props(s.factName)}>Workspace</dt>
                <dd {...stylex.props(s.factValue)}>{report.workspace.name}</dd>
              </>
            ) : null}
            <dt {...stylex.props(s.factName)}>Page</dt>
            <dd {...stylex.props(s.factValue, s.mono)}>{report.page_path}</dd>
            {report.element ? (
              <>
                <dt {...stylex.props(s.factName)}>Element</dt>
                <dd {...stylex.props(s.factValue)}>
                  {report.element.label ??
                    report.element.text ??
                    report.element.tag}
                  {report.element.role ? ` (${report.element.role})` : ""}
                </dd>
                <dt {...stylex.props(s.factName)}>Selector</dt>
                <dd {...stylex.props(s.factValue, s.mono)}>
                  {report.element.selector}
                </dd>
                {report.element.canvas_item_id ? (
                  <>
                    <dt {...stylex.props(s.factName)}>Canvas item</dt>
                    <dd {...stylex.props(s.factValue, s.mono)}>
                      {report.element.canvas_item_id}
                    </dd>
                  </>
                ) : null}
              </>
            ) : null}
            <dt {...stylex.props(s.factName)}>Screen</dt>
            <dd {...stylex.props(s.factValue)}>
              {report.client.viewport_width}×{report.client.viewport_height} @
              {report.client.device_pixel_ratio}x, {report.client.color_scheme}{" "}
              theme
            </dd>
            <dt {...stylex.props(s.factName)}>Browser</dt>
            <dd {...stylex.props(s.factValue, s.mono)}>
              {report.client.user_agent}
            </dd>
            <dt {...stylex.props(s.factName)}>Sent</dt>
            <dd {...stylex.props(s.factValue)}>
              {new Date(report.created_at).toLocaleString()}
            </dd>
          </dl>

          {report.screenshot ? (
            <a
              href={feedbackScreenshotUrl(report.id)}
              target="_blank"
              rel="noreferrer"
            >
              <img /* eslint-disable-line @next/next/no-img-element -- authenticated screenshot */
                src={feedbackScreenshotUrl(report.id)}
                alt={`Screenshot sent with the report from ${reporterName(report)}`}
                {...stylex.props(s.shot)}
              />
            </a>
          ) : null}

          {failure ? <Notice tone="danger">{failure}</Notice> : null}

          <div {...stylex.props(s.actions)}>
            <Button
              type="button"
              variant={report.status === "open" ? "primary" : "secondary"}
              size="sm"
              disabled={busy}
              onClick={() =>
                void update({
                  status: report.status === "open" ? "resolved" : "open",
                })
              }
            >
              {report.status === "open" ? (
                <>
                  <CircleCheck size={13} aria-hidden="true" />
                  Mark resolved
                </>
              ) : (
                <>
                  <RotateCcw size={13} aria-hidden="true" />
                  Reopen
                </>
              )}
            </Button>
            {report.github_issue_url ? (
              <>
                <ButtonLink
                  href={report.github_issue_url}
                  target="_blank"
                  rel="noreferrer"
                  variant="secondary"
                  size="sm"
                >
                  <ExternalLink size={13} aria-hidden="true" />
                  Open linked issue
                </ButtonLink>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void update({ github_issue_url: null })}
                >
                  <Unlink size={13} aria-hidden="true" />
                  Unlink
                </Button>
              </>
            ) : (
              <>
                <ButtonLink
                  href={githubIssueUrl(report)}
                  target="_blank"
                  rel="noreferrer"
                  variant="secondary"
                  size="sm"
                >
                  <ExternalLink size={13} aria-hidden="true" />
                  Draft GitHub issue
                </ButtonLink>
                <form
                  {...stylex.props(s.linkForm)}
                  onSubmit={(event) => {
                    event.preventDefault();
                    const url = issueUrl.trim();
                    if (url) void update({ github_issue_url: url });
                  }}
                >
                  <Field label="Filed issue link" xstyle={s.linkField}>
                    <TextInput
                      type="url"
                      placeholder="https://github.com/…/issues/123"
                      value={issueUrl}
                      onChange={(event) =>
                        setIssueUrl(event.currentTarget.value)
                      }
                      disabled={busy}
                    />
                  </Field>
                  <Button
                    type="submit"
                    variant="secondary"
                    size="sm"
                    disabled={busy || issueUrl.trim() === ""}
                  >
                    Save link
                  </Button>
                </form>
              </>
            )}
            <Button
              type="button"
              variant="danger"
              size="sm"
              disabled={busy}
              onClick={() => {
                if (
                  !window.confirm(
                    "Delete this report and its screenshot? This cannot be undone.",
                  )
                ) {
                  return;
                }
                void act(() => deleteFeedbackReport(report.id));
              }}
            >
              <Trash2 size={13} aria-hidden="true" />
              Delete
            </Button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

/** The operators' triage list: newest first, filtered by status, paged. */
export function FeedbackInbox() {
  const [filter, setFilter] = React.useState<Filter>("open");
  const { data, error, size, setSize, isValidating, mutate } =
    useSWRInfinite<FeedbackReportList>(
      (index, previous: FeedbackReportList | null) => {
        if (index > 0 && !previous?.next_before) return null;
        return feedbackReportsPath(
          filter === "all" ? null : filter,
          index === 0 ? null : (previous?.next_before ?? null),
          PAGE_SIZE,
        );
      },
    );
  const reports = data?.flatMap((page) => page.items) ?? [];
  const hasMore = Boolean(data?.[data.length - 1]?.next_before);

  if (error instanceof ApiError && error.status === 403) {
    return (
      <Notice tone="warning">
        Only operators of this deployment can read feedback reports.
      </Notice>
    );
  }

  return (
    <section {...stylex.props(s.root)} aria-label="Feedback reports">
      <div {...stylex.props(s.toolbar)}>
        <SegmentedControl<Filter>
          aria-label="Show reports"
          size="md"
          value={filter}
          options={FILTER_OPTIONS}
          onValueChange={setFilter}
          xstyle={s.filter}
        />
        <span {...stylex.props(s.meta)}>
          {data ? `${reports.length}${hasMore ? "+" : ""} shown` : "Loading…"}
        </span>
      </div>
      {error ? (
        <Notice
          tone="danger"
          action={
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => void mutate()}
            >
              Retry
            </Button>
          }
        >
          Feedback reports could not be loaded.
        </Notice>
      ) : null}
      {data && reports.length === 0 ? (
        <p {...stylex.props(s.empty)}>
          {filter === "open" ? "No open reports." : "No reports here."}
        </p>
      ) : null}
      <div {...stylex.props(s.list)}>
        {reports.map((report) => (
          <FeedbackReportRow
            key={report.id}
            report={report}
            onChanged={() => mutate()}
          />
        ))}
      </div>
      {hasMore ? (
        <Button
          type="button"
          variant="secondary"
          size="md"
          xstyle={s.more}
          disabled={isValidating}
          onClick={() => void setSize(size + 1)}
        >
          Load more
        </Button>
      ) : null}
    </section>
  );
}
