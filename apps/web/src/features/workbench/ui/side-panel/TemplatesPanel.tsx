"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ScrollArea } from "@base-ui/react/scroll-area";
import useSWR from "swr";
import {
  ExternalLink,
  FilePlus2,
  LayoutTemplate,
  LoaderCircle,
  Search,
  X,
} from "lucide-react";
import Link from "next/link";

import { graphAgeLabel } from "@/features/workspaces/WorkspaceGraphPanel";
import {
  instantiateWorkspaceTemplate,
  listWorkspaceTemplates,
  type GraphTemplate,
} from "@/lib/api";
import { panelStyles as s } from "./panel-styles";

function matchesTemplate(template: GraphTemplate, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (needle === "") return true;
  return `${template.name} ${template.description ?? ""} ${template.source_graph_name}`
    .toLowerCase()
    .includes(needle);
}

export function TemplatesPanel({
  workspaceId,
  onOpenGraph,
}: {
  workspaceId: string;
  onOpenGraph: (graphId: string) => void;
}) {
  const { data, isLoading, error } = useSWR(
    ["workspace-templates", workspaceId],
    () => listWorkspaceTemplates(workspaceId),
  );
  const [query, setQuery] = React.useState("");
  const [focusKey, setFocusKey] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [failure, setFailure] = React.useState<string | null>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

  const templates = React.useMemo(
    () =>
      (data?.templates ?? []).filter((item) => matchesTemplate(item, query)),
    [data, query],
  );
  const tabbableKey = focusKey ?? templates[0]?.id ?? null;

  async function createGraphFrom(template: GraphTemplate): Promise<void> {
    if (busyId) return;
    setBusyId(template.id);
    setFailure(null);
    try {
      const created = await instantiateWorkspaceTemplate(
        workspaceId,
        template.id,
        { destination_workspace_id: workspaceId, name: template.name },
      );
      onOpenGraph(created.graph_id);
    } catch (cause) {
      setFailure(
        cause instanceof Error && cause.message
          ? cause.message
          : `“${template.name}” could not be turned into a graph.`,
      );
    } finally {
      setBusyId(null);
    }
  }

  /** The action is the tabbable part of a template row, so arrows walk it. */
  function focusByStep(step: number): void {
    const list = [
      ...(listRef.current?.querySelectorAll<HTMLElement>(
        "[data-template-create]",
      ) ?? []),
    ];
    if (list.length === 0) return;
    const active = document.activeElement;
    const current = list.findIndex(
      (action) => action === active || action.dataset.templateId === focusKey,
    );
    const next = list[Math.min(list.length - 1, Math.max(0, current + step))];
    if (!next) return;
    setFocusKey(next.dataset.templateId ?? null);
    next.focus();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusByStep(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusByStep(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusByStep(-Number.MAX_SAFE_INTEGER);
    } else if (event.key === "End") {
      event.preventDefault();
      focusByStep(Number.MAX_SAFE_INTEGER);
    }
  }

  return (
    <div {...stylex.props(s.view)}>
      <div {...stylex.props(s.toolbar)}>
        <label {...stylex.props(s.search)}>
          <Search size={12} aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder="Filter templates"
            aria-label="Filter graph templates"
            onChange={(event) => setQuery(event.target.value)}
            {...stylex.props(s.searchInput)}
          />
          {query ? (
            <button
              type="button"
              aria-label="Clear template filter"
              {...stylex.props(s.iconButton)}
              onClick={() => setQuery("")}
            >
              <X size={12} />
            </button>
          ) : null}
        </label>
      </div>

      <div {...stylex.props(s.dropRegion)}>
        <ScrollArea.Root {...stylex.props(s.list)}>
          <ScrollArea.Viewport {...stylex.props(s.listViewport)}>
            <ScrollArea.Content {...stylex.props(s.listContent)}>
              {isLoading ? (
                <span role="status" {...stylex.props(s.notice)}>
                  <LoaderCircle size={12} {...stylex.props(s.spinner)} />{" "}
                  Loading templates…
                </span>
              ) : null}
              {error && !isLoading ? (
                <p role="alert" {...stylex.props(s.error)}>
                  Graph templates could not be loaded.
                </p>
              ) : null}
              {failure ? (
                <p role="alert" {...stylex.props(s.error)}>
                  {failure}
                </p>
              ) : null}
              {!isLoading && !error && templates.length === 0 ? (
                <p {...stylex.props(s.notice)}>
                  {data?.templates.length
                    ? `No template matches “${query.trim()}”.`
                    : "No graph templates in this workspace yet. Publish one from a graph you like."}
                </p>
              ) : null}
              <div
                ref={listRef}
                role="list"
                aria-label="Graph templates"
                onKeyDown={onKeyDown}
                {...stylex.props(s.listContent)}
              >
                {templates.map((template) => (
                  <TemplateRow
                    key={template.id}
                    template={template}
                    tabbable={tabbableKey === template.id}
                    busy={busyId === template.id}
                    onFocusRow={() => setFocusKey(template.id)}
                    onCreateGraph={() => void createGraphFrom(template)}
                  />
                ))}
              </div>
            </ScrollArea.Content>
          </ScrollArea.Viewport>
          <ScrollArea.Scrollbar {...stylex.props(s.scrollbar)}>
            <ScrollArea.Thumb {...stylex.props(s.thumb)} />
          </ScrollArea.Scrollbar>
        </ScrollArea.Root>
      </div>

      <footer role="status" {...stylex.props(s.statusBar)}>
        {`${templates.length} template${templates.length === 1 ? "" : "s"}`}
        <Link
          href="/templates"
          title="Manage graph templates"
          {...stylex.props(s.statusLink)}
        >
          <ExternalLink size={10} aria-hidden="true" />
          Manage
        </Link>
      </footer>
    </div>
  );
}

function TemplateRow({
  template,
  tabbable,
  busy,
  onFocusRow,
  onCreateGraph,
}: {
  template: GraphTemplate;
  tabbable: boolean;
  busy: boolean;
  onFocusRow: () => void;
  onCreateGraph: () => void;
}) {
  return (
    <div
      role="listitem"
      data-template-id={template.id}
      title={`${template.name} — save a new graph from this template`}
      {...stylex.props(s.fileRow)}
    >
      <span {...stylex.props(s.fileThumb)}>
        <LayoutTemplate size={11} aria-hidden="true" />
      </span>
      <span {...stylex.props(s.fileCopy)}>
        <span {...stylex.props(s.fileName)}>{template.name}</span>
        <span {...stylex.props(s.fileMeta)}>
          {template.node_count} nodes · {graphAgeLabel(template.updated_at)}
        </span>
        {template.description ? (
          <span {...stylex.props(s.fileMeta)}>{template.description}</span>
        ) : null}
      </span>
      <button
        type="button"
        data-template-create
        data-template-id={template.id}
        aria-label={`New graph from ${template.name}`}
        title="New graph from this template"
        disabled={busy}
        tabIndex={tabbable ? 0 : -1}
        onFocus={onFocusRow}
        onClick={onCreateGraph}
        {...stylex.props(s.rowAction)}
      >
        {busy ? (
          <LoaderCircle size={11} {...stylex.props(s.spinner)} />
        ) : (
          <FilePlus2 size={11} aria-hidden="true" />
        )}
      </button>
    </div>
  );
}
