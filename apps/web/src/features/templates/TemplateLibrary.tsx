"use client";

import * as React from "react";
import {
  Archive,
  ArrowRight,
  FileStack,
  LoaderCircle,
  RotateCcw,
  Search,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import useSWR from "swr";

import { BrandLoader } from "@/components/brand";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { workbenchGraphPath } from "@/features/workbench/routes";
import { WorkspaceRail } from "@/features/workspaces/WorkspaceLayout";
import { useWorkspaces } from "@/hooks/use-api";
import {
  archiveWorkspaceTemplate,
  instantiateWorkspaceTemplate,
  listWorkspaceGraphFolders,
  listWorkspaceTemplates,
} from "@/lib/api";
import type { GraphTemplate, Session, Workspace } from "@/lib/api";
import { ApiError } from "@/lib/api/client";

export interface LocatedTemplate {
  template: GraphTemplate;
  location: Workspace;
}

export function templateKey(item: LocatedTemplate): string {
  return `${item.location.id}:${item.template.id}`;
}

export function templateLocationLabel(
  workspace: Pick<Workspace, "kind" | "name">,
): string {
  return workspace.kind === "personal" ? "My graphs" : workspace.name;
}

export function filterLocatedTemplates(
  templates: readonly LocatedTemplate[],
  query: string,
): LocatedTemplate[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return [...templates];
  return templates.filter(({ template, location }) =>
    [
      template.name,
      template.description ?? "",
      template.source_graph_name,
      templateLocationLabel(location),
    ].some((value) => value.toLocaleLowerCase().includes(normalized)),
  );
}

export function nextTemplateKey(
  templates: readonly LocatedTemplate[],
  selectedKey: string | null,
  direction: 1 | -1,
): string | null {
  if (templates.length === 0) return null;
  const current = templates.findIndex(
    (item) => templateKey(item) === selectedKey,
  );
  const start = current < 0 ? (direction === 1 ? -1 : 0) : current;
  const index = (start + direction + templates.length) % templates.length;
  return templateKey(templates[index]!);
}

export function templatePreviewSummary(template: GraphTemplate): string {
  const nodes = `${template.node_count} ${template.node_count === 1 ? "node" : "nodes"}`;
  const edges = `${template.edge_count} ${template.edge_count === 1 ? "connection" : "connections"}`;
  return `${nodes} · ${edges}`;
}

export function templateUseErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return "You no longer have permission to create graphs in that location.";
    }
    if (error.status === 404) {
      return "This template or save location is no longer available. Refresh and try again.";
    }
    if (error.status === 422) return error.detail;
  }
  return "The graph could not be created. Your template is unchanged; try again.";
}

function useLocatedTemplates(
  userId: string,
  workspaces: readonly Workspace[] | undefined,
) {
  const key = workspaces
    ? ["templates", userId, ...workspaces.map((workspace) => workspace.id)]
    : null;
  return useSWR<LocatedTemplate[]>(key, async () => {
    const locations = workspaces ?? [];
    const lists = await Promise.all(
      locations.map((workspace) => listWorkspaceTemplates(workspace.id)),
    );
    return lists
      .flatMap((list, index) =>
        list.templates.map((template) => ({
          template,
          location: locations[index]!,
        })),
      )
      .sort((left, right) =>
        left.template.name.localeCompare(right.template.name),
      );
  });
}

function useWorkspaceFolders(workspaceId: string, enabled: boolean) {
  return useSWR(
    enabled && workspaceId ? ["graph-folders", workspaceId] : null,
    () => listWorkspaceGraphFolders(workspaceId),
  );
}

function creatorLabel(template: GraphTemplate, session: Session): string {
  if (template.created_by_user_id === session.user_id) return "You";
  if (template.created_by_user_id) return "Team member";
  return "Unknown creator";
}

export function TemplateLibrary() {
  const router = useRouter();
  const { session, logout } = useAuthSession();
  const { data: workspaces } = useWorkspaces(session.user_id);
  const {
    data: templates,
    error,
    isLoading,
    mutate,
  } = useLocatedTemplates(session.user_id, workspaces);
  const [query, setQuery] = React.useState("");
  const [selectedKey, setSelectedKey] = React.useState<string | null>(null);
  const [useOpen, setUseOpen] = React.useState(false);
  const [destinationId, setDestinationId] = React.useState("");
  const [graphName, setGraphName] = React.useState("");
  const [folderId, setFolderId] = React.useState("");
  const [useBusy, setUseBusy] = React.useState(false);
  const [useError, setUseError] = React.useState<string | null>(null);
  const [archiveError, setArchiveError] = React.useState<string | null>(null);
  const {
    data: folderList,
    error: folderError,
    isLoading: foldersLoading,
  } = useWorkspaceFolders(destinationId, useOpen);
  const useTriggerRef = React.useRef<HTMLButtonElement>(null);
  const restoreUseFocusRef = React.useRef(false);
  const searchRef = React.useRef<HTMLInputElement>(null);

  const filtered = React.useMemo(
    () => filterLocatedTemplates(templates ?? [], query),
    [query, templates],
  );
  const selected =
    filtered.find((item) => templateKey(item) === selectedKey) ??
    filtered[0] ??
    null;
  const createLocations = React.useMemo(
    () =>
      (workspaces ?? []).filter((workspace) =>
        workspace.capabilities.includes("create_graph"),
      ),
    [workspaces],
  );

  const openUse = () => {
    if (!selected) return;
    setGraphName(selected.template.name);
    const preferred = createLocations.find(
      (location) => location.id === selected.location.id,
    );
    setDestinationId((preferred ?? createLocations[0])?.id ?? "");
    setFolderId("");
    setUseError(null);
    setUseOpen(true);
  };

  React.useEffect(() => {
    if (!useOpen && restoreUseFocusRef.current) {
      restoreUseFocusRef.current = false;
      useTriggerRef.current?.focus();
    }
  }, [useOpen]);

  const closeUse = () => {
    restoreUseFocusRef.current = true;
    setUseOpen(false);
    setUseError(null);
  };

  const submitUse = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || !destinationId || !graphName.trim()) return;
    setUseBusy(true);
    setUseError(null);
    try {
      const created = await instantiateWorkspaceTemplate(
        selected.location.id,
        selected.template.id,
        {
          destination_workspace_id: destinationId,
          name: graphName.trim(),
          folder_id: folderId || null,
        },
      );
      const destination = createLocations.find(
        (location) => location.id === created.destination_workspace_id,
      );
      if (!destination) {
        setUseError(
          "The graph was created, but its save location is no longer listed.",
        );
        return;
      }
      router.push(workbenchGraphPath(destination.slug, created.graph_id));
    } catch (caught) {
      setUseError(templateUseErrorMessage(caught));
    } finally {
      setUseBusy(false);
    }
  };

  const archiveSelected = async () => {
    if (!selected) return;
    if (!window.confirm(`Archive “${selected.template.name}”?`)) return;
    setArchiveError(null);
    try {
      await archiveWorkspaceTemplate(
        selected.location.id,
        selected.template.id,
      );
      setUseOpen(false);
      await mutate();
      window.requestAnimationFrame(() => searchRef.current?.focus());
    } catch (caught) {
      setArchiveError(templateUseErrorMessage(caught));
    }
  };

  return (
    <div className="grafy-template-page">
      {workspaces ? (
        <WorkspaceRail
          workspaces={workspaces}
          session={session}
          onLogout={logout}
        />
      ) : null}
      <main className="grafy-template-library">
        <header className="grafy-template-library__header">
          <div>
            <p className="grafy-template-library__eyebrow">
              New graph / Library
            </p>
            <h1>Templates</h1>
            <p>Start an independent graph from an exact saved snapshot.</p>
          </div>
          <Link className="grafy-workspace-button" href="/">
            <Workflow size={14} aria-hidden="true" /> My graphs
          </Link>
        </header>

        <label className="grafy-template-search" htmlFor="template-search">
          <Search size={16} aria-hidden="true" />
          <input
            ref={searchRef}
            id="template-search"
            value={query}
            placeholder="Search templates, source graphs, or save locations"
            autoComplete="off"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={filtered.length > 0}
            aria-controls="template-results"
            aria-activedescendant={
              selected ? `template-option-${selected.template.id}` : undefined
            }
            onChange={(event) => {
              setQuery(event.target.value);
              setUseOpen(false);
            }}
            onKeyDown={(event) => {
              if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
              event.preventDefault();
              setSelectedKey(
                nextTemplateKey(
                  filtered,
                  selected ? templateKey(selected) : null,
                  event.key === "ArrowDown" ? 1 : -1,
                ),
              );
            }}
          />
          {query ? (
            <button type="button" onClick={() => setQuery("")}>
              Clear
            </button>
          ) : null}
        </label>

        {isLoading || !workspaces ? (
          <section className="grafy-template-state" aria-live="polite">
            <BrandLoader size={34} label="Loading templates" />
            <p>Loading templates from your graph locations…</p>
          </section>
        ) : error ? (
          <section className="grafy-template-state" role="alert">
            <h2>Templates could not be loaded</h2>
            <p>Check the connection, then retry without leaving this page.</p>
            <button
              className="grafy-workspace-button"
              type="button"
              onClick={() => void mutate()}
            >
              <RotateCcw size={14} aria-hidden="true" /> Retry
            </button>
          </section>
        ) : templates?.length === 0 ? (
          <section className="grafy-template-state">
            <FileStack size={28} aria-hidden="true" />
            <h2>No templates yet</h2>
            <p>
              Open a graph and choose Save as template to keep an independent
              starting point here.
            </p>
          </section>
        ) : filtered.length === 0 ? (
          <section className="grafy-template-state">
            <h2>No matching templates</h2>
            <p>Try a template name, source graph, or save location.</p>
            <button
              className="grafy-workspace-button"
              type="button"
              onClick={() => setQuery("")}
            >
              Clear search
            </button>
          </section>
        ) : (
          <div className="grafy-template-library__workspace">
            <section
              className="grafy-template-results"
              aria-label="Template results"
            >
              <div className="grafy-template-results__heading">
                <h2>
                  {filtered.length}{" "}
                  {filtered.length === 1 ? "template" : "templates"}
                </h2>
                <span>↑ ↓ to inspect</span>
              </div>
              <ul id="template-results" role="listbox" aria-label="Templates">
                {filtered.map((item) => {
                  const key = templateKey(item);
                  const active = selected
                    ? templateKey(selected) === key
                    : false;
                  return (
                    <li key={key}>
                      <button
                        id={`template-option-${item.template.id}`}
                        type="button"
                        role="option"
                        aria-selected={active}
                        className={active ? "is-selected" : undefined}
                        onClick={() => {
                          setSelectedKey(key);
                          setUseOpen(false);
                        }}
                      >
                        <span className="grafy-template-results__icon">
                          <FileStack size={16} aria-hidden="true" />
                        </span>
                        <span>
                          <strong>{item.template.name}</strong>
                          <small>
                            {templateLocationLabel(item.location)} · revision{" "}
                            {item.template.source_revision}
                          </small>
                        </span>
                        <ArrowRight size={14} aria-hidden="true" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>

            {selected ? (
              <aside className="grafy-template-preview" aria-live="polite">
                <div className="grafy-template-preview__topline">
                  <span>Preview</span>
                  <span>{templateLocationLabel(selected.location)}</span>
                </div>
                <h2>{selected.template.name}</h2>
                <p className="grafy-template-preview__description">
                  {selected.template.description ?? "No description provided."}
                </p>
                <dl className="grafy-template-preview__facts">
                  <div>
                    <dt>Snapshot</dt>
                    <dd>{templatePreviewSummary(selected.template)}</dd>
                  </div>
                  <div>
                    <dt>Source</dt>
                    <dd>
                      {selected.template.source_graph_name} · revision{" "}
                      {selected.template.source_revision}
                    </dd>
                  </div>
                  <div>
                    <dt>Created by</dt>
                    <dd>{creatorLabel(selected.template, session)}</dd>
                  </div>
                </dl>

                {useOpen ? (
                  <form className="grafy-template-use" onSubmit={submitUse}>
                    <div className="grafy-template-use__heading">
                      <h3>Create independent graph</h3>
                      <p>
                        Later edits to either graph will not affect the other.
                      </p>
                    </div>
                    <label>
                      Graph name
                      <input
                        value={graphName}
                        onChange={(event) => setGraphName(event.target.value)}
                        maxLength={160}
                        autoFocus
                        required
                      />
                    </label>
                    <label>
                      Save location
                      <select
                        value={destinationId}
                        onChange={(event) => {
                          setDestinationId(event.target.value);
                          setFolderId("");
                        }}
                        required
                      >
                        {createLocations.map((location) => (
                          <option key={location.id} value={location.id}>
                            {templateLocationLabel(location)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Folder <span>optional</span>
                      <select
                        value={folderId}
                        onChange={(event) => setFolderId(event.target.value)}
                        disabled={foldersLoading || Boolean(folderError)}
                      >
                        <option value="">
                          {foldersLoading ? "Loading folders…" : "Unfiled"}
                        </option>
                        {(folderList?.folders ?? []).map((folder) => (
                          <option key={folder.id} value={folder.id}>
                            {folder.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    {folderError ? (
                      <p className="grafy-template-use__error" role="alert">
                        Folders could not be loaded. Choose Unfiled or try
                        again.
                      </p>
                    ) : null}
                    {useError ? (
                      <p className="grafy-template-use__error" role="alert">
                        {useError}
                      </p>
                    ) : null}
                    <div className="grafy-template-use__actions">
                      <button
                        className="grafy-workspace-button"
                        type="button"
                        onClick={closeUse}
                        disabled={useBusy}
                      >
                        Cancel
                      </button>
                      <button
                        className="grafy-workspace-button grafy-workspace-button--primary"
                        type="submit"
                        disabled={
                          useBusy || !destinationId || !graphName.trim()
                        }
                      >
                        {useBusy ? (
                          <LoaderCircle
                            className="grafy-template-spin"
                            size={14}
                          />
                        ) : (
                          <ArrowRight size={14} />
                        )}
                        {useBusy
                          ? "Creating…"
                          : useError
                            ? "Try again"
                            : "Create and open"}
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="grafy-template-preview__actions">
                    <button
                      ref={useTriggerRef}
                      type="button"
                      className="grafy-workspace-button grafy-workspace-button--primary"
                      disabled={createLocations.length === 0}
                      title={
                        createLocations.length === 0
                          ? "You need permission to create graphs in a save location"
                          : undefined
                      }
                      onClick={openUse}
                    >
                      Use template <ArrowRight size={14} aria-hidden="true" />
                    </button>
                    {selected.location.capabilities.includes(
                      "manage_template_library",
                    ) ? (
                      <button
                        type="button"
                        className="grafy-workspace-button"
                        onClick={() => void archiveSelected()}
                      >
                        <Archive size={14} aria-hidden="true" /> Archive
                      </button>
                    ) : null}
                  </div>
                )}
                {createLocations.length === 0 ? (
                  <p className="grafy-template-preview__permission">
                    You can inspect templates, but you need graph creation
                    permission in a save location to use one.
                  </p>
                ) : null}
                {archiveError ? (
                  <p className="grafy-template-use__error" role="alert">
                    {archiveError}
                  </p>
                ) : null}
                <Link
                  className="grafy-template-preview__source"
                  href={workbenchGraphPath(
                    selected.location.slug,
                    selected.template.source_graph_id,
                  )}
                >
                  Open source graph
                </Link>
              </aside>
            ) : null}
          </div>
        )}
      </main>
    </div>
  );
}
