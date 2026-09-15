"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import useSWR from "swr";
import { ArrowUpRight, Library, LoaderCircle, X } from "lucide-react";

import { listLibraryArtifacts, type LibraryItem } from "@/lib/api";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

const s = stylex.create({
  drawer: {
    position: "absolute",
    zIndex: 35,
    top: {
      default: "66px",
      "@media (max-width: 720px)": "12px",
    },
    right: {
      default: "12px",
      "@media (max-width: 720px)": "var(--grafy-mobile-drawer-right, 12px)",
    },
    bottom: {
      default: "12px",
      "@media (max-width: 720px)": "auto",
    },
    display: "flex",
    flexDirection: "column",
    width: { default: "380px", "@media (max-width: 720px)": "calc(100vw - 24px)" },
    maxHeight: "min(620px, calc(100vh - 90px))",
    overflow: "hidden",
    backgroundColor: "#ffffff",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "#d7dbe0",
    borderRadius: "10px",
    boxShadow: "0 12px 34px rgba(15, 23, 42, 0.18)",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "10px 12px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: "#e8ebef",
  },
  title: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    fontSize: "13px",
    fontWeight: 600,
    color: "#1f2937",
  },
  spacer: { flex: 1 },
  close: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: "24px",
    height: "24px",
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: "transparent",
    color: "#4b5563",
    cursor: "pointer",
    ":hover": { backgroundColor: "#f1f3f5" },
  },
  body: { display: "flex", flexDirection: "column", overflowY: "auto" },
  empty: { padding: "22px 14px", fontSize: "13px", color: "#6b7280" },
  row: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
    alignItems: "flex-start",
    width: "100%",
    padding: "9px 12px",
    borderWidth: 0,
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: "#f1f3f5",
    backgroundColor: "transparent",
    textAlign: "left",
    cursor: "pointer",
    ":hover": { backgroundColor: "#f8fafc" },
  },
  rowSelected: { backgroundColor: "#eef4ff" },
  name: {
    fontSize: "13px",
    fontWeight: 500,
    color: "#111827",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    maxWidth: "100%",
  },
  line: {
    fontSize: "11.5px",
    color: "#6b7280",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    maxWidth: "100%",
  },
  detail: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    padding: "12px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: "#e8ebef",
    backgroundColor: "#fbfcfd",
  },
  detailLabel: {
    fontSize: "10.5px",
    fontWeight: 600,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    color: "#6b7280",
  },
  detailValue: { fontSize: "12.5px", color: "#111827" },
  detailMono: { fontFamily: MONO, fontSize: "11.5px", color: "#374151" },
  runLink: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    alignSelf: "flex-start",
    marginTop: "2px",
    padding: "4px 8px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "#c7d2fe",
    borderRadius: "6px",
    backgroundColor: "#eef2ff",
    color: "#3730a3",
    fontSize: "12px",
    cursor: "pointer",
  },
  loading: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "18px 14px",
    fontSize: "13px",
    color: "#6b7280",
  },
});

function provenanceLine(item: LibraryItem): string {
  const { provenance } = item;
  if (provenance.source === "upload") {
    return provenance.original_filename
      ? `uploaded · ${provenance.original_filename}`
      : "uploaded";
  }
  const parts = [
    provenance.graph_title,
    provenance.node_title,
    provenance.graph_revision == null
      ? null
      : `revision ${provenance.graph_revision}`,
    "from a run",
  ].filter((part): part is string => Boolean(part));
  return parts.join(" · ");
}

export function LibraryDrawer({
  workspaceId,
  onClose,
  onOpenRun,
}: {
  workspaceId: string;
  onClose: () => void;
  onOpenRun: (graphId: string, executionId: string) => void;
}) {
  const { data, isLoading } = useSWR(["library-artifacts", workspaceId], () =>
    listLibraryArtifacts(workspaceId),
  );
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const items = data?.items ?? [];
  const selected = items.find((item) => item.artifact.artifact_id === selectedId);

  return (
    <section aria-label="Library" {...stylex.props(s.drawer)}>
      <header {...stylex.props(s.header)}>
        <span {...stylex.props(s.title)}>
          <Library size={14} />
          Library
        </span>
        <span {...stylex.props(s.spacer)} />
        <button
          type="button"
          aria-label="Close Library"
          onClick={onClose}
          {...stylex.props(s.close)}
        >
          <X size={14} />
        </button>
      </header>
      <div {...stylex.props(s.body)}>
        {isLoading ? (
          <span {...stylex.props(s.loading)}>
            <LoaderCircle size={14} />
            Loading…
          </span>
        ) : items.length === 0 ? (
          <p {...stylex.props(s.empty)}>
            Nothing in the Library yet. Save a Run artifact or upload a file to
            record where it came from.
          </p>
        ) : (
          items.map((item) => (
            <button
              key={item.artifact.artifact_id}
              type="button"
              aria-pressed={selectedId === item.artifact.artifact_id}
              onClick={() => setSelectedId(item.artifact.artifact_id)}
              {...stylex.props(
                s.row,
                selectedId === item.artifact.artifact_id && s.rowSelected,
              )}
            >
              <span {...stylex.props(s.name)}>{item.name}</span>
              <span {...stylex.props(s.line)}>{provenanceLine(item)}</span>
            </button>
          ))
        )}
      </div>
      {selected ? (
        <div {...stylex.props(s.detail)}>
          <span {...stylex.props(s.detailLabel)}>Provenance</span>
          <span {...stylex.props(s.detailValue)}>
            {provenanceLine(selected)}
          </span>
          {selected.provenance.execution_id ? (
            <span {...stylex.props(s.detailMono)}>
              run {selected.provenance.execution_id}
            </span>
          ) : null}
          {selected.run?.finished_at ? (
            <span {...stylex.props(s.detailValue)}>
              finished {new Date(selected.run.finished_at).toLocaleString()}
            </span>
          ) : null}
          {selected.run ? (
            <button
              type="button"
              {...stylex.props(s.runLink)}
              onClick={() =>
                onOpenRun(selected.run!.graph_id, selected.run!.execution_id)
              }
            >
              <ArrowUpRight size={12} />
              Open in execution history
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
