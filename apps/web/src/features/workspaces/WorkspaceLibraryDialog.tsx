"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowUpRight, Library, Search } from "lucide-react";
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
  listWorkspaceModules,
  type ModuleLibraryEntry,
  type Workspace,
} from "@/lib/api";
import { useNodeRegistry } from "@/hooks/use-api";
import { workbenchGraphPath } from "@/features/workbench/routes";
import { artifactTypeKey } from "@/features/workbench/canvas/artifact-type-key";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeTooltip,
  type ArtifactTypeCatalog,
} from "@/features/workbench/canvas/artifact-type-label";
import { tokens } from "@/lib/stylex/tokens.stylex";

function artifactTypeLabel(
  port: NonNullable<ModuleLibraryEntry["inputs"]>[number],
  artifactTypes: ArtifactTypeCatalog,
) {
  return formatArtifactTypeLabel(port.artifact_type, artifactTypes);
}

function moduleSearchText(module: ModuleLibraryEntry): string {
  const ports = [...(module.inputs ?? []), ...(module.outputs ?? [])];
  return [
    module.name,
    module.description ?? "",
    module.source_graph_id,
    String(module.current_library_release ?? ""),
    // Search still matches a type by its raw identity, not just its title.
    ...ports.flatMap((port) => [
      port.name,
      artifactTypeKey(port.artifact_type),
    ]),
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
  artifactTypes,
}: {
  label: "Inputs" | "Outputs";
  ports: NonNullable<ModuleLibraryEntry["inputs"]>;
  artifactTypes: ArtifactTypeCatalog;
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
              {port.name} ·{" "}
              <span title={formatArtifactTypeTooltip(port.artifact_type)}>
                {artifactTypeLabel(port, artifactTypes)}
              </span>
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
}: {
  workspace: Workspace;
  focusedModuleId?: string | null;
  onOpenSourceGraph?: (graphId: string) => void;
}) {
  const router = useRouter();
  // The Module contract names its ports' types, so it reads them the way the
  // workspace's own catalog does.
  const { data: registry } = useNodeRegistry(workspace.id);
  const artifactTypes = registry?.artifact_types ?? null;
  const [query, setQuery] = React.useState("");

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
            {workspace.capabilities.includes("publish_module") ? null : (
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
                    <ContractPorts
                      label="Inputs"
                      ports={module.inputs ?? []}
                      artifactTypes={artifactTypes}
                    />
                    <ContractPorts
                      label="Outputs"
                      ports={module.outputs ?? []}
                      artifactTypes={artifactTypes}
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
                </div>
              </li>
            );
          })}
        </ul>
      )}
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
}: {
  workspace: Workspace;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  triggerLabel?: string;
  showTrigger?: boolean;
  focusedModuleId?: string | null;
  onOpenSourceGraph?: (graphId: string) => void;
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
              Search the published contracts
              {workspace.kind === "personal" ? " you keep" : " this Team offers"}{" "}
              and open the graph behind any of them.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {open ? (
              <WorkspaceModuleLibrary
                workspace={workspace}
                focusedModuleId={focusedModuleId}
                onOpenSourceGraph={onOpenSourceGraph}
              />
            ) : null}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}
