"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpRight,
  ArrowUpFromLine,
  Check,
  CircleDashed,
  Plus,
} from "lucide-react";
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
  publishModuleRelease,
  type ModuleLibraryEntry,
  type PublishModuleReleaseRequest,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

export interface ModuleBoundarySummary {
  id: string;
  direction: "input" | "output";
  portName: string | null;
  description: string | null;
  artifactType: string | null;
  connectionCount: number;
}

export interface ModuleSetupReadinessInput {
  graphSaved: boolean;
  revisionCurrent: boolean;
  canPublish: boolean;
  outputBoundaryCount: number;
  contractValidation: "unchecked" | "validated" | "failed";
  publishedRelease: number | null;
}

export interface ModuleSetupCheck {
  id:
    | "saved"
    | "revision"
    | "permission"
    | "interface"
    | "validation"
    | "publication";
  label: string;
  detail: string;
  status: "complete" | "blocked" | "pending";
}

export function moduleSetupReadiness(
  input: ModuleSetupReadinessInput,
): readonly ModuleSetupCheck[] {
  const prerequisitesReady =
    input.graphSaved &&
    input.revisionCurrent &&
    input.canPublish &&
    input.outputBoundaryCount > 0;

  return [
    {
      id: "saved",
      label: "Saved graph revision",
      detail: input.graphSaved
        ? "This graph has a durable source revision."
        : "Save this graph before it can become a Module.",
      status: input.graphSaved ? "complete" : "blocked",
    },
    {
      id: "revision",
      label: "Current graph revision",
      detail: input.revisionCurrent
        ? "The canvas matches the saved revision."
        : "Save the latest canvas changes before publishing.",
      status: input.revisionCurrent ? "complete" : "blocked",
    },
    {
      id: "permission",
      label: "Publish permission",
      detail: input.canPublish
        ? "Your current access can publish Modules here."
        : "Publishing requires Editor or Owner access here.",
      status: input.canPublish ? "complete" : "blocked",
    },
    {
      id: "interface",
      label: "Module interface",
      detail:
        input.outputBoundaryCount > 0
          ? `${input.outputBoundaryCount} contract output${input.outputBoundaryCount === 1 ? "" : "s"} present. Inputs are optional.`
          : "Add and connect at least one Module Output boundary. Inputs are optional.",
      status: input.outputBoundaryCount > 0 ? "complete" : "blocked",
    },
    {
      id: "validation",
      label: "Contract validation",
      detail:
        input.contractValidation === "validated"
          ? "The server accepted this exact revision as a Module contract."
          : input.contractValidation === "failed"
            ? "The server rejected this revision. Use the validation error below to repair the contract."
            : "The server validates boundary wiring, types, names, and nested Modules when you publish.",
      status:
        input.contractValidation === "validated"
          ? "complete"
          : input.contractValidation === "failed"
            ? "blocked"
            : "pending",
    },
    {
      id: "publication",
      label: "Publication readiness",
      detail:
        input.publishedRelease !== null
          ? `Release ${input.publishedRelease} is the current library release.`
          : prerequisitesReady
            ? "Ready for server validation and publication."
            : "Complete the blocked items above to publish.",
      status:
        input.publishedRelease !== null
          ? "complete"
          : prerequisitesReady
            ? "pending"
            : "blocked",
    },
  ];
}

const s = stylex.create({
  layout: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 260px",
    gap: tokens.space5,
  },
  flow: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.space5,
    minWidth: 0,
  },
  section: {
    display: "grid",
    gap: tokens.space3,
    paddingTop: tokens.space1,
  },
  dividedSection: {
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    paddingTop: tokens.space5,
  },
  sectionHeading: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: tokens.space3,
  },
  heading: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    fontWeight: 700,
  },
  sectionIndex: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
  },
  copy: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.55,
  },
  form: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)",
    gap: tokens.space3,
  },
  field: {
    display: "grid",
    alignContent: "start",
    gap: "5px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    textTransform: "uppercase",
  },
  control: {
    width: "100%",
    minHeight: "34px",
    padding: `7px ${tokens.space2}`,
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
    boxSizing: "border-box",
  },
  textarea: {
    minHeight: "76px",
    resize: "vertical",
  },
  boundaryToolbar: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.space2,
  },
  boundaryList: {
    display: "grid",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  boundaryRow: {
    display: "grid",
    gridTemplateColumns: "24px minmax(0, 1fr) auto",
    alignItems: "center",
    gap: tokens.space2,
    minHeight: "48px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  boundaryIcon: {
    color: tokens.colorMuted,
  },
  boundaryName: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
  },
  boundaryMeta: {
    margin: "2px 0 0",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  validationNote: {
    display: "flex",
    alignItems: "flex-start",
    gap: tokens.space2,
    padding: tokens.space3,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  error: {
    display: "flex",
    alignItems: "flex-start",
    gap: tokens.space2,
    margin: 0,
    padding: tokens.space3,
    borderLeftWidth: 2,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDanger,
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  success: {
    display: "grid",
    gridTemplateColumns: "20px minmax(0, 1fr)",
    gap: tokens.space2,
    padding: tokens.space3,
    borderLeftWidth: 2,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorSuccess,
    backgroundColor: tokens.colorAccentSoft,
  },
  successTitle: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
  },
  successActions: {
    display: "flex",
    flexWrap: "wrap",
    gap: tokens.space2,
    marginTop: tokens.space2,
  },
  publishActions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space3,
  },
  checklist: {
    alignSelf: "start",
    position: "sticky",
    top: 0,
    display: "grid",
    gap: tokens.space1,
    paddingLeft: tokens.space4,
    borderLeftWidth: 1,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDivider,
  },
  checkRow: {
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    gap: tokens.space2,
    padding: `${tokens.space2} 0`,
  },
  complete: {
    color: tokens.colorSuccess,
  },
  pending: {
    color: tokens.colorWarning,
  },
  blocked: {
    color: tokens.colorDanger,
  },
  checkLabel: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
  },
  checkDetail: {
    margin: "2px 0 0",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  mobileLayout: {
    "@media (max-width: 720px)": {
      gridTemplateColumns: "1fr",
    },
  },
  mobileForm: {
    "@media (max-width: 560px)": {
      gridTemplateColumns: "1fr",
    },
  },
  mobileChecklist: {
    "@media (max-width: 720px)": {
      position: "static",
      paddingLeft: 0,
      paddingTop: tokens.space4,
      borderLeftWidth: 0,
      borderTopWidth: 1,
      borderTopStyle: "solid",
      borderTopColor: tokens.colorDivider,
    },
  },
});

function StatusIcon({ status }: { status: ModuleSetupCheck["status"] }) {
  if (status === "complete") {
    return <Check size={15} aria-hidden="true" {...stylex.props(s.complete)} />;
  }
  if (status === "blocked") {
    return (
      <AlertTriangle
        size={15}
        aria-hidden="true"
        {...stylex.props(s.blocked)}
      />
    );
  }
  return (
    <CircleDashed size={15} aria-hidden="true" {...stylex.props(s.pending)} />
  );
}

function boundaryConnectionLabel(boundary: ModuleBoundarySummary): string {
  if (boundary.connectionCount === 0) return "not connected";
  if (boundary.connectionCount === 1) return "1 connection";
  return `${boundary.connectionCount} connections`;
}

export function PublishModuleDialog({
  open,
  onOpenChange,
  workspaceId,
  sourceGraphId,
  graphName,
  revision,
  isDirty,
  canPublish,
  canEdit,
  boundaries,
  canAddInputBoundary,
  canAddOutputBoundary,
  onAddBoundary,
  onSelectBoundary,
  onViewModule,
  onOpenSourceGraph,
  onPublished,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  sourceGraphId: string | null;
  graphName: string;
  revision: number | null;
  isDirty: boolean;
  canPublish: boolean;
  canEdit: boolean;
  boundaries: readonly ModuleBoundarySummary[];
  canAddInputBoundary: boolean;
  canAddOutputBoundary: boolean;
  onAddBoundary?: (direction: ModuleBoundarySummary["direction"]) => void;
  onSelectBoundary?: (nodeId: string) => void;
  onViewModule?: (moduleId: string) => void;
  onOpenSourceGraph?: (graphId: string) => void;
  onPublished?: (module: ModuleLibraryEntry) => void | Promise<unknown>;
}) {
  const [name, setName] = React.useState(graphName);
  const [description, setDescription] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [publishedModule, setPublishedModule] =
    React.useState<ModuleLibraryEntry | null>(null);

  const {
    data,
    error: moduleListError,
    isLoading: moduleListLoading,
    mutate,
  } = useSWR(open ? ["workspace-modules", workspaceId] : null, () =>
    listWorkspaceModules(workspaceId),
  );
  const listedModule = sourceGraphId
    ? (data?.modules.find(
        (module) => module.source_graph_id === sourceGraphId,
      ) ?? null)
    : null;
  const existingModule =
    publishedModule?.source_graph_id === sourceGraphId
      ? publishedModule
      : listedModule;

  const setDialogOpen = (nextOpen: boolean) => {
    if (!nextOpen) {
      setName(graphName);
      setDescription("");
      setBusy(false);
      setError(null);
      setPublishedModule(null);
    }
    onOpenChange(nextOpen);
  };

  const inputBoundaries = boundaries.filter(
    (boundary) => boundary.direction === "input",
  );
  const outputBoundaries = boundaries.filter(
    (boundary) => boundary.direction === "output",
  );
  const revisionWasValidated = Boolean(
    existingModule &&
    revision !== null &&
    existingModule.current_library_release === revision &&
    !isDirty,
  );
  const checks = moduleSetupReadiness({
    graphSaved: sourceGraphId !== null && revision !== null,
    revisionCurrent: sourceGraphId !== null && revision !== null && !isDirty,
    canPublish,
    outputBoundaryCount: outputBoundaries.length,
    contractValidation: revisionWasValidated
      ? "validated"
      : error
        ? "failed"
        : "unchecked",
    publishedRelease: revisionWasValidated
      ? (existingModule?.current_library_release ?? null)
      : null,
  });
  const isLaterRelease = Boolean(existingModule?.releases?.length);
  const publishReady =
    sourceGraphId !== null &&
    revision !== null &&
    !isDirty &&
    canPublish &&
    outputBoundaries.length > 0 &&
    !moduleListLoading &&
    !moduleListError &&
    (isLaterRelease || name.trim() !== "");

  const confirm = async () => {
    if (!sourceGraphId || revision === null || !publishReady) return;
    setBusy(true);
    setError(null);
    try {
      let body: PublishModuleReleaseRequest = {
        source_graph_id: sourceGraphId,
        revision,
      };
      if (!isLaterRelease) {
        body = {
          source_graph_id: sourceGraphId,
          revision,
          name: name.trim(),
          description: description.trim() || null,
        };
      }
      const publishedEntry = await publishModuleRelease(workspaceId, body);
      await mutate(
        (current) => {
          if (!current) return { modules: [publishedEntry] };
          const alreadyListed = current.modules.some(
            (candidate) => candidate.id === publishedEntry.id,
          );
          return {
            modules: alreadyListed
              ? current.modules.map((candidate) =>
                  candidate.id === publishedEntry.id
                    ? publishedEntry
                    : candidate,
                )
              : [...current.modules, publishedEntry],
          };
        },
        { revalidate: false },
      );
      setPublishedModule(publishedEntry);
      await onPublished?.(publishedEntry);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The server could not validate and publish this release.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setDialogOpen}>
      <DialogContent size="wide">
        <DialogHeader>
          <DialogTitle>Module setup</DialogTitle>
          <DialogDescription>
            Define the contract, check the exact saved revision, and publish it
            as a Module in your library.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div {...stylex.props(s.layout, s.mobileLayout)}>
            <div {...stylex.props(s.flow)}>
              <section
                aria-labelledby="module-details-heading"
                {...stylex.props(s.section)}
              >
                <div {...stylex.props(s.sectionHeading)}>
                  <h3 id="module-details-heading" {...stylex.props(s.heading)}>
                    Details
                  </h3>
                  <span {...stylex.props(s.sectionIndex)}>01</span>
                </div>
                <p {...stylex.props(s.copy)}>
                  {isLaterRelease
                    ? "These details describe the library entry. Publishing creates another immutable release."
                    : "Choose the name and description people will see in the Module library."}
                </p>
                {isLaterRelease ? (
                  <div>
                    <p {...stylex.props(s.boundaryName)}>
                      {existingModule?.name}
                    </p>
                    <p {...stylex.props(s.copy)}>
                      {existingModule?.description ?? "No Module description."}
                    </p>
                  </div>
                ) : (
                  <div {...stylex.props(s.form, s.mobileForm)}>
                    <label {...stylex.props(s.field)}>
                      Module name
                      <input
                        {...stylex.props(s.control)}
                        value={name}
                        maxLength={160}
                        onChange={(event) => setName(event.currentTarget.value)}
                      />
                    </label>
                    <label {...stylex.props(s.field)}>
                      Description (optional)
                      <textarea
                        {...stylex.props(s.control, s.textarea)}
                        rows={3}
                        maxLength={1000}
                        value={description}
                        onChange={(event) =>
                          setDescription(event.currentTarget.value)
                        }
                      />
                    </label>
                  </div>
                )}
              </section>

              <section
                aria-labelledby="module-interface-heading"
                {...stylex.props(s.section, s.dividedSection)}
              >
                <div {...stylex.props(s.sectionHeading)}>
                  <h3
                    id="module-interface-heading"
                    {...stylex.props(s.heading)}
                  >
                    Interface
                  </h3>
                  <span {...stylex.props(s.sectionIndex)}>02</span>
                </div>
                <p {...stylex.props(s.copy)}>
                  Module Input and Module Output nodes define the contract
                  ports. Add boundaries here, then configure their names, types,
                  and wiring on the canvas.
                </p>
                <div {...stylex.props(s.boundaryToolbar)}>
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    disabled={!canEdit || !canAddInputBoundary}
                    title={
                      canAddInputBoundary
                        ? "Add an optional contract input boundary to the canvas"
                        : "The Module Input node is unavailable in this registry"
                    }
                    onClick={() => onAddBoundary?.("input")}
                  >
                    <Plus size={13} /> Add input
                  </button>
                  <button
                    type="button"
                    className="grafy-workspace-button"
                    disabled={!canEdit || !canAddOutputBoundary}
                    title={
                      canAddOutputBoundary
                        ? "Add a required contract output boundary to the canvas"
                        : "The Module Output node is unavailable in this registry"
                    }
                    onClick={() => onAddBoundary?.("output")}
                  >
                    <Plus size={13} /> Add output
                  </button>
                </div>
                {boundaries.length === 0 ? (
                  <p {...stylex.props(s.copy)}>
                    No Module boundaries yet. Start with an output, connect a
                    workflow result to it, then save the graph.
                  </p>
                ) : (
                  <div
                    aria-label="Module boundaries"
                    {...stylex.props(s.boundaryList)}
                  >
                    {[...inputBoundaries, ...outputBoundaries].map(
                      (boundary) => (
                        <div key={boundary.id} {...stylex.props(s.boundaryRow)}>
                          {boundary.direction === "input" ? (
                            <ArrowDownToLine
                              size={15}
                              aria-hidden="true"
                              {...stylex.props(s.boundaryIcon)}
                            />
                          ) : (
                            <ArrowUpFromLine
                              size={15}
                              aria-hidden="true"
                              {...stylex.props(s.boundaryIcon)}
                            />
                          )}
                          <div>
                            <p {...stylex.props(s.boundaryName)}>
                              {boundary.portName ??
                                `Unconfigured ${boundary.direction}`}
                            </p>
                            <p {...stylex.props(s.boundaryMeta)}>
                              {boundary.direction} ·{" "}
                              {boundary.artifactType ?? "type not bound"} ·{" "}
                              {boundaryConnectionLabel(boundary)}
                            </p>
                            {boundary.description ? (
                              <p {...stylex.props(s.boundaryMeta)}>
                                {boundary.description}
                              </p>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            className="grafy-workspace-button"
                            onClick={() => {
                              setDialogOpen(false);
                              onSelectBoundary?.(boundary.id);
                            }}
                          >
                            Edit on canvas
                          </button>
                        </div>
                      ),
                    )}
                  </div>
                )}
              </section>

              <section
                aria-labelledby="module-validate-heading"
                {...stylex.props(s.section, s.dividedSection)}
              >
                <div {...stylex.props(s.sectionHeading)}>
                  <h3 id="module-validate-heading" {...stylex.props(s.heading)}>
                    Validate
                  </h3>
                  <span {...stylex.props(s.sectionIndex)}>03</span>
                </div>
                <div {...stylex.props(s.validationNote)}>
                  <CircleDashed
                    size={15}
                    aria-hidden="true"
                    {...stylex.props(s.pending)}
                  />
                  <p {...stylex.props(s.copy)}>
                    The backend is the source of truth for the Module contract.
                    Validation runs with Publish and checks this exact saved
                    revision; a rejected contract is not published.
                  </p>
                </div>
                {moduleListError ? (
                  <p role="alert" {...stylex.props(s.error)}>
                    <AlertTriangle size={15} aria-hidden="true" />
                    <span>
                      The current Module releases could not be loaded. Close
                      setup and retry before publishing this graph.
                    </span>
                  </p>
                ) : null}
                {error ? (
                  <p role="alert" {...stylex.props(s.error)}>
                    <AlertTriangle size={15} aria-hidden="true" />
                    <span>{error}</span>
                  </p>
                ) : null}
              </section>

              <section
                aria-labelledby="module-publish-heading"
                {...stylex.props(s.section, s.dividedSection)}
              >
                <div {...stylex.props(s.sectionHeading)}>
                  <h3 id="module-publish-heading" {...stylex.props(s.heading)}>
                    Publish
                  </h3>
                  <span {...stylex.props(s.sectionIndex)}>04</span>
                </div>
                <p {...stylex.props(s.copy)}>
                  {isLaterRelease
                    ? `Existing callers stay pinned to release ${existingModule?.current_library_release ?? "their chosen revision"}. Publishing revision ${revision ?? "—"} does not change those calls; people choose when to upgrade.`
                    : "The first publish creates a reusable library entry and an immutable release pinned to this graph revision."}
                </p>

                {publishedModule ? (
                  <div role="status" {...stylex.props(s.success)}>
                    <Check
                      size={16}
                      aria-hidden="true"
                      {...stylex.props(s.complete)}
                    />
                    <div>
                      <p {...stylex.props(s.successTitle)}>
                        Published release{" "}
                        {publishedModule.current_library_release}
                      </p>
                      <p {...stylex.props(s.copy)}>
                        This exact revision is now the current library release.
                        Existing pinned calls were not changed.
                      </p>
                      <div {...stylex.props(s.successActions)}>
                        <button
                          type="button"
                          className="grafy-workspace-button grafy-workspace-button--primary"
                          onClick={() => {
                            setDialogOpen(false);
                            onViewModule?.(publishedModule.id);
                          }}
                        >
                          View module <ArrowUpRight size={13} />
                        </button>
                        <button
                          type="button"
                          className="grafy-workspace-button"
                          onClick={() =>
                            onOpenSourceGraph?.(publishedModule.source_graph_id)
                          }
                        >
                          Open source
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div {...stylex.props(s.publishActions)}>
                    <span {...stylex.props(s.copy)}>
                      {revision === null
                        ? "No saved revision"
                        : `Source revision ${revision}`}
                    </span>
                    <button
                      type="button"
                      className="grafy-workspace-button grafy-workspace-button--primary"
                      disabled={busy || !publishReady}
                      onClick={() => void confirm()}
                    >
                      {busy
                        ? "Validating contract…"
                        : moduleListLoading
                          ? "Loading Module…"
                          : "Publish release"}
                    </button>
                  </div>
                )}
              </section>
            </div>

            <aside
              aria-label="Module readiness checklist"
              {...stylex.props(s.checklist, s.mobileChecklist)}
            >
              <h3 {...stylex.props(s.heading)}>Readiness</h3>
              {checks.map((check) => (
                <div
                  key={check.id}
                  data-status={check.status}
                  {...stylex.props(s.checkRow)}
                >
                  <StatusIcon status={check.status} />
                  <div>
                    <p {...stylex.props(s.checkLabel)}>{check.label}</p>
                    <p {...stylex.props(s.checkDetail)}>{check.detail}</p>
                  </div>
                </div>
              ))}
            </aside>
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
