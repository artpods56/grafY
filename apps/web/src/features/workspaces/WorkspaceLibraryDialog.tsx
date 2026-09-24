"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowUpRight,
  Check,
  Copy,
  Library,
  Search,
  ShieldAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import useSWR from "swr";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  deprecateModule,
  importModuleRelease,
  listWorkspaceModules,
  withdrawModule,
  type ModuleLibraryEntry,
  type Workspace,
} from "@/lib/api";
import { useWorkspaces } from "@/hooks/use-api";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { workbenchGraphPath } from "@/features/workbench/routes";
import { tokens } from "@/lib/stylex/tokens.stylex";

function artifactTypeLabel(
  port: NonNullable<ModuleLibraryEntry["inputs"]>[number],
) {
  return `${port.artifact_type.id}@${port.artifact_type.schema_version}`;
}

function moduleSearchText(module: ModuleLibraryEntry): string {
  const ports = [...(module.inputs ?? []), ...(module.outputs ?? [])];
  return [
    module.name,
    module.description ?? "",
    module.publication_state,
    module.source_graph_id,
    String(module.current_library_release ?? ""),
    ...ports.flatMap((port) => [port.name, artifactTypeLabel(port)]),
  ]
    .join(" ")
    .toLocaleLowerCase();
}

export function filterWorkspaceModules(
  modules: readonly ModuleLibraryEntry[],
  query: string,
): readonly ModuleLibraryEntry[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return modules;
  return modules.filter((module) =>
    moduleSearchText(module).includes(normalized),
  );
}

function libraryLabel(workspace: Workspace): string {
  return workspace.kind === "personal"
    ? "My Module library"
    : `${workspace.name} Team Modules`;
}

function destinationLabel(workspace: Workspace): string {
  return workspace.kind === "personal"
    ? `My graphs · ${workspace.name}`
    : `Team · ${workspace.name}`;
}

const s = stylex.create({
  surface: {
    display: "grid",
    gap: tokens.space4,
  },
  toolbar: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: tokens.space3,
  },
  search: {
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    alignItems: "center",
    gap: tokens.space2,
    minHeight: "38px",
    padding: `0 ${tokens.space3}`,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
  },
  searchInput: {
    width: "100%",
    borderWidth: 0,
    outline: "none",
    backgroundColor: "transparent",
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
  },
  count: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
  message: {
    display: "flex",
    alignItems: "flex-start",
    gap: tokens.space2,
    margin: 0,
    padding: tokens.space3,
    borderLeftWidth: 2,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorSuccess,
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
  error: {
    borderLeftColor: tokens.colorDanger,
    backgroundColor: tokens.colorDangerHover,
  },
  empty: {
    display: "grid",
    gap: tokens.space3,
    padding: `${tokens.space5} 0`,
  },
  emptyTitle: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    fontWeight: 700,
  },
  copyText: {
    margin: 0,
    maxWidth: "620px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.55,
  },
  steps: {
    display: "grid",
    gap: tokens.space2,
    margin: 0,
    paddingLeft: tokens.space5,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  list: {
    display: "grid",
    margin: 0,
    padding: 0,
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    listStyle: "none",
    maxHeight: "54vh",
    overflow: "auto",
  },
  module: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: tokens.space4,
    padding: `${tokens.space4} 0`,
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  focusedModule: {
    backgroundColor: tokens.colorAccentSoft,
  },
  moduleMain: {
    display: "grid",
    gap: tokens.space2,
    minWidth: 0,
  },
  moduleHeading: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: tokens.space2,
  },
  moduleName: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    fontWeight: 700,
  },
  state: {
    display: "inline-flex",
    alignItems: "center",
    minHeight: "20px",
    padding: `0 ${tokens.space2}`,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "999px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    textTransform: "capitalize",
  },
  deprecated: {
    borderColor: tokens.colorWarning,
    color: tokens.colorWarning,
  },
  metadata: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.space2,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  contract: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
    gap: tokens.space3,
    marginTop: tokens.space1,
  },
  contractGroup: {
    display: "grid",
    alignContent: "start",
    gap: tokens.space1,
  },
  contractLabel: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    textTransform: "uppercase",
  },
  portList: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.space1,
    margin: 0,
    padding: 0,
    listStyle: "none",
  },
  port: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  actions: {
    display: "flex",
    alignContent: "start",
    alignItems: "flex-start",
    justifyContent: "flex-end",
    flexWrap: "wrap",
    gap: tokens.space2,
    maxWidth: "310px",
  },
  actionPanel: {
    display: "grid",
    gap: tokens.space3,
    padding: tokens.space4,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  panelHeading: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: tokens.space3,
  },
  panelTitle: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    fontWeight: 700,
  },
  field: {
    display: "grid",
    gap: "5px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    textTransform: "uppercase",
  },
  select: {
    width: "100%",
    minHeight: "36px",
    padding: `0 ${tokens.space2}`,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    outline: "none",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 400,
    textTransform: "none",
  },
  panelActions: {
    display: "flex",
    justifyContent: "flex-end",
    flexWrap: "wrap",
    gap: tokens.space2,
  },
  mobileModule: {
    "@media (max-width: 720px)": {
      gridTemplateColumns: "1fr",
    },
  },
  mobileContract: {
    "@media (max-width: 520px)": {
      gridTemplateColumns: "1fr",
    },
  },
  mobileActions: {
    "@media (max-width: 720px)": {
      justifyContent: "flex-start",
      maxWidth: "none",
    },
  },
});

function ContractPorts({
  label,
  ports,
}: {
  label: "Inputs" | "Outputs";
  ports: NonNullable<ModuleLibraryEntry["inputs"]>;
}) {
  return (
    <div {...stylex.props(s.contractGroup)}>
      <p {...stylex.props(s.contractLabel)}>{label}</p>
      <ul
        aria-label={`Module ${label.toLocaleLowerCase()}`}
        {...stylex.props(s.portList)}
      >
        {ports.length ? (
          ports.map((port) => (
            <li
              key={`${port.direction}:${port.name}`}
              {...stylex.props(s.port)}
            >
              {port.name} · {artifactTypeLabel(port)}
              {label === "Inputs"
                ? port.required
                  ? " · required"
                  : " · optional"
                : ""}
            </li>
          ))
        ) : (
          <li {...stylex.props(s.port)}>None</li>
        )}
      </ul>
    </div>
  );
}

export function WorkspaceModuleLibrary({
  workspace,
  focusedModuleId = null,
  onOpenSourceGraph,
  onLibraryChanged,
}: {
  workspace: Workspace;
  focusedModuleId?: string | null;
  onOpenSourceGraph?: (graphId: string) => void;
  onLibraryChanged?: () => void | Promise<unknown>;
}) {
  const router = useRouter();
  const { session } = useAuthSession();
  const { data: workspaces = [] } = useWorkspaces(session.user_id);
  const [query, setQuery] = React.useState("");
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [importTarget, setImportTarget] =
    React.useState<ModuleLibraryEntry | null>(null);
  const [withdrawTarget, setWithdrawTarget] =
    React.useState<ModuleLibraryEntry | null>(null);
  const [destinationId, setDestinationId] = React.useState("");

  const {
    data,
    error: libraryError,
    mutate,
    isLoading,
  } = useSWR(["workspace-modules", workspace.id], () =>
    listWorkspaceModules(workspace.id),
  );
  const modules = data?.modules ?? [];
  const visibleModules = filterWorkspaceModules(modules, query);
  const importDestinations = workspaces.filter(
    (candidate) =>
      candidate.id !== workspace.id &&
      candidate.capabilities.includes("create_graph"),
  );
  const canPublish = workspace.capabilities.includes("publish_module");
  const canManageLibrary = workspace.capabilities.includes(
    "manage_module_library",
  );

  const applyModuleUpdate = async (updated: ModuleLibraryEntry) => {
    await mutate(
      (current) => {
        if (!current) return { modules: [updated] };
        if (updated.publication_state === "withdrawn") {
          return {
            modules: current.modules.filter(
              (module) => module.id !== updated.id,
            ),
          };
        }
        return {
          modules: current.modules.map((module) =>
            module.id === updated.id ? updated : module,
          ),
        };
      },
      { revalidate: false },
    );
    await onLibraryChanged?.();
  };

  const runDeprecate = async (module: ModuleLibraryEntry) => {
    setBusyId(module.id);
    setError(null);
    setMessage(null);
    try {
      const updated = await deprecateModule(workspace.id, module.id);
      await applyModuleUpdate(updated);
      setMessage(
        `${module.name} is deprecated. Existing pinned calls keep working.`,
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message} Retry deprecating this Module.`
          : "The Module could not be deprecated. Retry the action.",
      );
    } finally {
      setBusyId(null);
    }
  };

  const runWithdraw = async () => {
    if (!withdrawTarget) return;
    const target = withdrawTarget;
    setBusyId(target.id);
    setError(null);
    setMessage(null);
    try {
      const updated = await withdrawModule(workspace.id, target.id);
      await applyModuleUpdate(updated);
      setWithdrawTarget(null);
      setMessage(
        `${target.name} was withdrawn from the library. Existing pinned calls keep working.`,
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message} The Module is still in the library; retry or cancel.`
          : "The Module could not be withdrawn. It remains in the library; retry or cancel.",
      );
    } finally {
      setBusyId(null);
    }
  };

  const runImport = async () => {
    if (!importTarget || !destinationId) return;
    const destination = importDestinations.find(
      (candidate) => candidate.id === destinationId,
    );
    if (!destination) return;
    setBusyId(importTarget.id);
    setError(null);
    setMessage(null);
    try {
      const imported = await importModuleRelease(destinationId, {
        source_workspace_id: workspace.id,
        source_module_id: importTarget.id,
        revision: importTarget.current_library_release ?? undefined,
      });
      setImportTarget(null);
      setDestinationId("");
      await onLibraryChanged?.();
      router.push(workbenchGraphPath(destination.slug, imported.graph_id));
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message} Choose another destination or retry the import.`
          : "The copy could not be imported. Choose another destination or retry.",
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div {...stylex.props(s.surface)}>
      <div {...stylex.props(s.toolbar)}>
        <label {...stylex.props(s.search)}>
          <Search size={15} aria-hidden="true" />
          <input
            aria-label="Search Modules"
            placeholder="Search Modules, ports, types, or source graph…"
            value={query}
            {...stylex.props(s.searchInput)}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <span aria-live="polite" {...stylex.props(s.count)}>
          {visibleModules.length} of {modules.length}
        </span>
      </div>

      {error ? (
        <p role="alert" {...stylex.props(s.message, s.error)}>
          <ShieldAlert size={15} aria-hidden="true" />
          <span>{error}</span>
        </p>
      ) : null}
      {message ? (
        <p role="status" {...stylex.props(s.message)}>
          <Check size={15} aria-hidden="true" />
          <span>{message}</span>
        </p>
      ) : null}

      {libraryError ? (
        <div role="alert" {...stylex.props(s.empty)}>
          <p {...stylex.props(s.emptyTitle)}>Couldn’t load Modules</p>
          <p {...stylex.props(s.copyText)}>
            The current library is unavailable. Check your connection or access,
            then retry without leaving this surface.
          </p>
          <button
            type="button"
            className="grafy-workspace-button"
            onClick={() => void mutate()}
          >
            Retry loading Modules
          </button>
        </div>
      ) : isLoading ? (
        <div role="status" {...stylex.props(s.empty)}>
          <p {...stylex.props(s.emptyTitle)}>Loading Modules…</p>
          <p {...stylex.props(s.copyText)}>
            Reading {workspace.kind === "personal" ? "your" : "the Team"}{" "}
            library and its published contracts.
          </p>
        </div>
      ) : modules.length === 0 ? (
        <div {...stylex.props(s.empty)}>
          <p {...stylex.props(s.emptyTitle)}>No published Modules yet</p>
          <p {...stylex.props(s.copyText)}>
            Open a source graph, choose Module in the Workbench actions, and
            declare the contract before publishing its first release.
          </p>
          <ol {...stylex.props(s.steps)}>
            <li>Add and connect at least one Module Output boundary.</li>
            <li>
              Add Module Input boundaries for values callers should provide.
            </li>
            <li>Save the graph, then Publish release from Module setup.</li>
            {canPublish ? null : (
              <li>Publishing requires Editor or Owner access here.</li>
            )}
          </ol>
        </div>
      ) : visibleModules.length === 0 ? (
        <div {...stylex.props(s.empty)}>
          <p {...stylex.props(s.emptyTitle)}>
            No Modules match “{query.trim()}”
          </p>
          <p {...stylex.props(s.copyText)}>
            Search by Module name, port, artifact type, release, or source
            graph.
          </p>
          <button
            type="button"
            className="grafy-workspace-button"
            onClick={() => setQuery("")}
          >
            Clear search
          </button>
        </div>
      ) : (
        <ul aria-label="Modules" {...stylex.props(s.list)}>
          {visibleModules.map((module) => {
            const releaseCount = module.releases?.length ?? 0;
            const canImport =
              module.publication_state !== "withdrawn" &&
              importDestinations.length > 0;
            return (
              <li
                key={module.id}
                data-module-id={module.id}
                {...stylex.props(
                  s.module,
                  s.mobileModule,
                  focusedModuleId === module.id ? s.focusedModule : null,
                )}
              >
                <div {...stylex.props(s.moduleMain)}>
                  <div {...stylex.props(s.moduleHeading)}>
                    <h3 {...stylex.props(s.moduleName)}>{module.name}</h3>
                    <span
                      {...stylex.props(
                        s.state,
                        module.publication_state === "deprecated"
                          ? s.deprecated
                          : null,
                      )}
                    >
                      {module.publication_state}
                    </span>
                  </div>
                  <div {...stylex.props(s.metadata)}>
                    <span>
                      Current release {module.current_library_release ?? "—"}
                    </span>
                    <span>
                      {releaseCount} immutable release
                      {releaseCount === 1 ? "" : "s"}
                    </span>
                    <span>Source graph {module.source_graph_id}</span>
                  </div>
                  {module.description ? (
                    <p {...stylex.props(s.copyText)}>{module.description}</p>
                  ) : null}
                  <div
                    aria-label={`${module.name} contract`}
                    {...stylex.props(s.contract, s.mobileContract)}
                  >
                    <ContractPorts label="Inputs" ports={module.inputs ?? []} />
                    <ContractPorts
                      label="Outputs"
                      ports={module.outputs ?? []}
                    />
                  </div>
                </div>

                <div {...stylex.props(s.actions, s.mobileActions)}>
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    onClick={() =>
                      onOpenSourceGraph
                        ? onOpenSourceGraph(module.source_graph_id)
                        : router.push(
                            workbenchGraphPath(
                              workspace.slug,
                              module.source_graph_id,
                            ),
                          )
                    }
                  >
                    Open source graph <ArrowUpRight size={13} />
                  </button>
                  {canManageLibrary &&
                  module.publication_state === "published" ? (
                    <button
                      type="button"
                      className="grafy-workspace-button"
                      disabled={busyId === module.id}
                      onClick={() => void runDeprecate(module)}
                    >
                      Deprecate
                    </button>
                  ) : null}
                  {canManageLibrary ? (
                    <button
                      type="button"
                      className="grafy-workspace-button"
                      disabled={busyId === module.id}
                      onClick={() => {
                        setError(null);
                        setMessage(null);
                        setWithdrawTarget(module);
                      }}
                    >
                      Withdraw from library
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    disabled={busyId === module.id || !canImport}
                    title={
                      importDestinations.length
                        ? "Create an independent Module copy in another Team or My graphs"
                        : "No other Team or My graphs location allows graph creation"
                    }
                    onClick={() => {
                      setError(null);
                      setMessage(null);
                      setImportTarget(module);
                      setDestinationId(importDestinations[0]?.id ?? "");
                    }}
                  >
                    <Copy size={13} /> Import copy to Team
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {withdrawTarget ? (
        <section
          aria-labelledby="withdraw-module-heading"
          {...stylex.props(s.actionPanel)}
        >
          <div {...stylex.props(s.panelHeading)}>
            <div>
              <h3 id="withdraw-module-heading" {...stylex.props(s.panelTitle)}>
                Withdraw {withdrawTarget.name} from the library?
              </h3>
              <p {...stylex.props(s.copyText)}>
                It will disappear from browse and new inserts. Existing Module
                calls keep resolving their pinned releases. This is not a hard
                delete.
              </p>
            </div>
          </div>
          <div {...stylex.props(s.panelActions)}>
            <button
              type="button"
              className="grafy-workspace-button"
              disabled={busyId === withdrawTarget.id}
              onClick={() => setWithdrawTarget(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="grafy-workspace-button grafy-workspace-button--primary"
              disabled={busyId === withdrawTarget.id}
              onClick={() => void runWithdraw()}
            >
              {busyId === withdrawTarget.id
                ? "Withdrawing…"
                : "Confirm withdraw"}
            </button>
          </div>
        </section>
      ) : null}

      {importTarget ? (
        <section
          aria-labelledby="import-module-heading"
          {...stylex.props(s.actionPanel)}
        >
          <div {...stylex.props(s.panelHeading)}>
            <div>
              <h3 id="import-module-heading" {...stylex.props(s.panelTitle)}>
                Import copy of {importTarget.name}
              </h3>
              <p {...stylex.props(s.copyText)}>
                This copies release{" "}
                {importTarget.current_library_release ?? "—"} into the
                destination as a new source graph and published Module. It is
                independent—not a live cross-Team link.
              </p>
            </div>
          </div>
          <label {...stylex.props(s.field)}>
            Team or My graphs destination
            <select
              {...stylex.props(s.select)}
              value={destinationId}
              onChange={(event) => setDestinationId(event.currentTarget.value)}
            >
              {importDestinations.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {destinationLabel(candidate)}
                </option>
              ))}
            </select>
          </label>
          <div {...stylex.props(s.panelActions)}>
            <button
              type="button"
              className="grafy-workspace-button"
              disabled={busyId === importTarget.id}
              onClick={() => setImportTarget(null)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="grafy-workspace-button grafy-workspace-button--primary"
              disabled={!destinationId || busyId === importTarget.id}
              onClick={() => void runImport()}
            >
              {busyId === importTarget.id
                ? "Importing copy…"
                : "Confirm import"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function WorkspaceLibraryDialog({
  workspace,
  open: controlledOpen,
  onOpenChange,
  triggerLabel,
  showTrigger = true,
  focusedModuleId = null,
  onOpenSourceGraph,
  onLibraryChanged,
}: {
  workspace: Workspace;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  triggerLabel?: string;
  showTrigger?: boolean;
  focusedModuleId?: string | null;
  onOpenSourceGraph?: (graphId: string) => void;
  onLibraryChanged?: () => void | Promise<unknown>;
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;
  const label = triggerLabel ?? libraryLabel(workspace);

  return (
    <>
      {showTrigger ? (
        <button
          type="button"
          className="grafy-workspace-button"
          onClick={() => setOpen(true)}
        >
          <Library size={14} /> {label}
        </button>
      ) : null}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="wide">
          <DialogHeader>
            <DialogTitle>{libraryLabel(workspace)}</DialogTitle>
            <DialogDescription>
              Search published contracts, open source graphs, and steward what
              {workspace.kind === "personal"
                ? " you keep"
                : " this Team offers"}{" "}
              for reuse. Withdrawn Modules leave browse while pinned calls keep
              working.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {open ? (
              <WorkspaceModuleLibrary
                workspace={workspace}
                focusedModuleId={focusedModuleId}
                onOpenSourceGraph={onOpenSourceGraph}
                onLibraryChanged={onLibraryChanged}
              />
            ) : null}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}
