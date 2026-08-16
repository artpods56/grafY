"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { AlertTriangle, Check, FileCode2, LoaderCircle, ShieldCheck } from "lucide-react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  AgentBuildReview,
  AgentBuildReviewFileContent,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  layout: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(190px, 0.32fr) minmax(0, 1fr)",
      "@media (max-width: 720px)": "1fr",
    },
    gap: tokens.space4,
    minHeight: "min(620px, 72vh)",
  },
  sidebar: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.space4,
    minWidth: 0,
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.space2,
  },
  heading: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
  },
  meta: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  testStatus: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    padding: tokens.space2,
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: tokens.radiusMd,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  success: { color: tokens.colorSuccess },
  danger: { color: tokens.colorDanger },
  fileList: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    maxHeight: "250px",
    overflowY: "auto",
  },
  fileButton: {
    display: "grid",
    gridTemplateColumns: "16px minmax(0, 1fr) auto",
    alignItems: "center",
    gap: tokens.space2,
    width: "100%",
    padding: `${tokens.space2} ${tokens.space2}`,
    border: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: tokens.colorText,
    textAlign: "left",
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    ':hover': { backgroundColor: tokens.colorHover },
  },
  selectedFile: { backgroundColor: tokens.colorAccentSoft },
  path: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  change: {
    color: tokens.colorMuted,
    textTransform: "uppercase",
    fontSize: "9px",
    letterSpacing: "0.04em",
  },
  review: {
    display: "flex",
    flexDirection: "column",
    minWidth: 0,
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: tokens.radiusMd,
    overflow: "hidden",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  reviewHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space3,
    padding: `${tokens.space2} ${tokens.space3}`,
    borderBottom: `1px solid ${tokens.colorBorder}`,
    backgroundColor: tokens.colorSurface,
  },
  code: {
    flex: 1,
    margin: 0,
    padding: tokens.space3,
    overflow: "auto",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.55,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    whiteSpace: "pre",
  },
  empty: {
    display: "grid",
    placeItems: "center",
    flex: 1,
    padding: tokens.space6,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    textAlign: "center",
  },
  capabilities: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.space1,
    margin: 0,
    paddingLeft: tokens.space4,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  digest: {
    display: "block",
    overflowWrap: "anywhere",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: "9px",
  },
  footer: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space3,
    marginTop: tokens.space4,
    paddingTop: tokens.space3,
    borderTop: `1px solid ${tokens.colorDivider}`,
  },
  error: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    margin: 0,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeSm,
  },
});

export interface AgentBuildReviewDialogProps {
  open: boolean;
  nodeTitle: string;
  review: AgentBuildReview | null;
  selectedFile: AgentBuildReviewFileContent | null;
  selectedPath: string | null;
  loading: boolean;
  fileLoading: boolean;
  error: string | null;
  pendingAction: "approving" | "publishing" | null;
  capabilityApprovalId: string | null;
  onOpenChange: (open: boolean) => void;
  onSelectFile: (path: string) => void;
  onApprove: () => void;
  onPublish: () => void;
}

export function AgentBuildReviewDialog({
  open,
  nodeTitle,
  review,
  selectedFile,
  selectedPath,
  loading,
  fileLoading,
  error,
  pendingAction,
  capabilityApprovalId,
  onOpenChange,
  onSelectFile,
  onApprove,
  onPublish,
}: AgentBuildReviewDialogProps) {
  const selectedChange = review?.changes.find(
    (change) => change.path === selectedPath,
  );
  const capabilities = review?.build.capabilities ?? null;
  const capabilityItems = capabilities
    ? [
        ...capabilities.outbound_http_origins.map((origin) => `HTTP: ${origin}`),
        ...capabilities.secret_refs.map((secret) => `Secret: ${secret}`),
        ...capabilities.object_store.map(
          (access) => `Object store ${access.scope}: ${access.prefix}`,
        ),
      ]
    : [];
  const displayContent = selectedChange?.unified_diff ?? selectedFile?.content ?? "";
  const reviewPaths = review
    ? [...new Set([
        ...review.files.map((file) => file.path),
        ...review.changes.map((change) => change.path),
      ])]
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="wide">
        <DialogHeader>
          <DialogTitle>Review generated build</DialogTitle>
          <DialogDescription>
            Inspect the exact tested source and capability manifest before
            approving {nodeTitle}.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {loading ? (
            <div role="status" {...stylex.props(s.empty)}>
              <span><LoaderCircle size={16} /> Loading verified build…</span>
            </div>
          ) : review ? (
            <div {...stylex.props(s.layout)}>
              <aside aria-label="Build review summary" {...stylex.props(s.sidebar)}>
                <section {...stylex.props(s.section)}>
                  <h3 {...stylex.props(s.heading)}>Verification</h3>
                  <div {...stylex.props(s.testStatus)}>
                    {review.tests.passed ? (
                      <Check size={14} aria-hidden="true" {...stylex.props(s.success)} />
                    ) : (
                      <AlertTriangle size={14} aria-hidden="true" {...stylex.props(s.danger)} />
                    )}
                    {review.tests.passed
                      ? `${review.tests.file_count} test file${review.tests.file_count === 1 ? "" : "s"} passed`
                      : "Generated tests did not pass"}
                  </div>
                  <p {...stylex.props(s.meta)}>
                    {review.previous_release_revision === null
                      ? "First release"
                      : `Compared with release ${review.previous_release_revision}`}
                  </p>
                </section>

                <section {...stylex.props(s.section)}>
                  <h3 {...stylex.props(s.heading)}>Files</h3>
                  <div aria-label="Reviewable files" {...stylex.props(s.fileList)}>
                    {reviewPaths.map((path) => {
                      const change = review.changes.find(
                        (candidate) => candidate.path === path,
                      );
                      return (
                        <button
                          key={path}
                          type="button"
                          aria-pressed={selectedPath === path}
                          {...stylex.props(
                            s.fileButton,
                            selectedPath === path && s.selectedFile,
                          )}
                          onClick={() => onSelectFile(path)}
                        >
                          <FileCode2 size={13} aria-hidden="true" />
                          <span {...stylex.props(s.path)}>{path}</span>
                          {change ? (
                            <span {...stylex.props(s.change)}>{change.change}</span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                </section>

                <section {...stylex.props(s.section)}>
                  <h3 {...stylex.props(s.heading)}>Capabilities</h3>
                  {capabilityItems.length ? (
                    <ul {...stylex.props(s.capabilities)}>
                      {capabilityItems.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  ) : (
                    <p {...stylex.props(s.meta)}>No external capabilities requested.</p>
                  )}
                  {capabilities ? (
                    <p {...stylex.props(s.meta)}>
                      Runtime: {capabilities.runtime.cpu_millis}m CPU · {capabilities.runtime.memory_megabytes} MB · {capabilities.runtime.wall_time_seconds}s
                      <span {...stylex.props(s.digest)}>{capabilities.digest}</span>
                    </p>
                  ) : null}
                </section>
              </aside>

              <section aria-label="Generated source" {...stylex.props(s.review)}>
                <div {...stylex.props(s.reviewHeader)}>
                  <strong {...stylex.props(s.heading)}>{selectedPath ?? "Select a file"}</strong>
                  {selectedFile ? (
                    <span {...stylex.props(s.meta)}>{selectedFile.byte_count} bytes</span>
                  ) : null}
                </div>
                {fileLoading ? (
                  <div role="status" {...stylex.props(s.empty)}>Loading source…</div>
                ) : displayContent ? (
                  <pre {...stylex.props(s.code)}>{displayContent}</pre>
                ) : (
                  <div {...stylex.props(s.empty)}>Choose a file to inspect its verified contents.</div>
                )}
              </section>
            </div>
          ) : null}

          {error ? (
            <p role="alert" {...stylex.props(s.error)}>
              <AlertTriangle size={14} aria-hidden="true" /> {error}
            </p>
          ) : null}

          {review ? (
            <div {...stylex.props(s.footer)}>
              <span {...stylex.props(s.meta)}>
                <ShieldCheck size={13} aria-hidden="true" /> Approval is bound to this exact capability digest.
              </span>
              {capabilityApprovalId ? (
                <button
                  type="button"
                  className="grafy-workspace-button grafy-workspace-button--primary"
                  disabled={pendingAction !== null}
                  onClick={onPublish}
                >
                  {pendingAction === "publishing" ? "Publishing…" : "Publish node"}
                </button>
              ) : (
                <button
                  type="button"
                  className="grafy-workspace-button grafy-workspace-button--primary"
                  disabled={
                    pendingAction !== null ||
                    !review.tests.passed ||
                    !review.build.capabilities
                  }
                  onClick={onApprove}
                >
                  {pendingAction === "approving"
                    ? "Approving…"
                    : "Approve exact capabilities"}
                </button>
              )}
            </div>
          ) : null}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
