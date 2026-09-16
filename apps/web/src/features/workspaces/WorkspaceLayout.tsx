"use client";

import * as React from "react";
import { Popover } from "@base-ui/react/popover";
import {
  ChevronsUpDown,
  LoaderCircle,
  LogOut,
  Mail,
  Menu,
  Plus,
  Save,
  Settings,
  Users,
  Workflow,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useSWRConfig } from "swr";

import { BrandIcon, BrandWordmark } from "@/components/brand";
import { useTheme } from "@/components/theme";
import { ThresholdStatus } from "@/components/threshold-status";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { useWorkbenchChrome } from "@/features/workbench/ui/WorkbenchChromeContext";
import {
  NEW_GRAPH_ROUTE_ID,
  workbenchGraphPath,
} from "@/features/workbench/routes";
import {
  useGraphSummaryRefresh,
  useMyWorkspaceInvitations,
  useSavedGraphs,
  useWorkspaces,
} from "@/hooks/use-api";
import { useMediaQuery } from "@/hooks/use-media-query";
import {
  acceptWorkspaceInvitation,
  declineWorkspaceInvitation,
  type SavedGraphSummary,
  type Session,
  type Workspace,
  type WorkspaceRole,
} from "@/lib/api";
import {
  deleteSavedGraphRemote,
  renameSavedGraphRemote,
} from "./graph-actions";
import { GraphRowMenu, promptGraphRename } from "./GraphRowMenu";
import { sortGraphsByRecency } from "./WorkspaceGraphPanel";

export interface WorkspaceContextValue {
  workspace: Workspace;
  workspaces: readonly Workspace[];
  refreshWorkspaces: () => Promise<readonly Workspace[] | undefined>;
}

export type WorkspaceRouteAccessState = "available" | "missing" | "revoked";

const RAIL_COLLAPSED_KEY = "grafy-workspace-rail-collapsed";
const RAIL_EXPANDED_WIDTH = 200;
const RAIL_COLLAPSED_WIDTH = 64;
const RAIL_COLLAPSE_THRESHOLD = 132;
const RAIL_DESKTOP_QUERY = "(min-width: 861px)";
const RAIL_MOBILE_QUERY = "(max-width: 620px)";
const roleDescriptionsForInvitation: Record<WorkspaceRole, string> = {
  viewer: "View graphs, artifacts, history, and shared activity.",
  editor: "View, create, edit, and run graphs.",
  owner: "Full access, including member and workspace administration.",
};

const railCollapsedListeners = new Set<() => void>();

function subscribeRailCollapsed(listener: () => void): () => void {
  railCollapsedListeners.add(listener);
  return () => railCollapsedListeners.delete(listener);
}

function readRailCollapsed(): boolean {
  try {
    const stored = window.localStorage.getItem(RAIL_COLLAPSED_KEY);
    return stored === "1";
  } catch {
    return false;
  }
}

function writeRailCollapsed(next: boolean): void {
  try {
    window.localStorage.setItem(RAIL_COLLAPSED_KEY, next ? "1" : "0");
  } catch {
    // Ignore storage errors.
  }
  for (const listener of railCollapsedListeners) listener();
}

function clearRailWidthOverride(): void {
  const root = document.documentElement;
  root.style.removeProperty("--grafy-rail-width");
  root.classList.remove("grafy-rail-resizing");
  document.body.classList.remove("grafy-rail-resizing");
}

function setRailWidthOverride(width: number): void {
  const root = document.documentElement;
  root.style.setProperty("--grafy-rail-width", `${Math.round(width)}px`);
  root.classList.add("grafy-rail-resizing");
  document.body.classList.add("grafy-rail-resizing");
}

function useRailCollapsed(): [boolean, (next: boolean) => void] {
  const collapsed = React.useSyncExternalStore(
    subscribeRailCollapsed,
    readRailCollapsed,
    () => false,
  );

  React.useEffect(() => {
    document.documentElement.dataset.railCollapsed = collapsed
      ? "true"
      : "false";
  }, [collapsed]);

  const setCollapsed = React.useCallback((next: boolean) => {
    writeRailCollapsed(next);
  }, []);

  return [collapsed, setCollapsed];
}

export function workspaceCanManageMembers(workspace: Workspace): boolean {
  return workspace.capabilities.includes("manage_members");
}

/** Graph currently open in the workbench, or null on non-graph routes. */
export function workspaceRouteGraphId(pathname: string): string | null {
  const match = /\/graphs\/([^/?#]+)/.exec(pathname);
  const graphId = match?.[1];
  if (!graphId || graphId === NEW_GRAPH_ROUTE_ID) return null;
  return decodeURIComponent(graphId);
}

const RAIL_RECENT_GRAPH_LIMIT = 6;

export function workspaceRouteAccessState(
  workspaceSlug: string,
  workspace: Workspace | undefined,
  previouslyResolvedWorkspace: Pick<Workspace, "slug" | "id"> | undefined,
): WorkspaceRouteAccessState {
  if (workspace) return "available";
  return previouslyResolvedWorkspace?.slug === workspaceSlug
    ? "revoked"
    : "missing";
}

/** User-facing save/share location label. */
export function workspaceDisplayName(
  workspace: Pick<Workspace, "name" | "kind">,
): string {
  if (workspace.kind === "personal") return "My graphs";
  return workspace.name;
}

/** Label shown in the rail's workspace switcher; defaults to "Personal". */
export function workspaceSelectorLabel(
  workspace: Pick<Workspace, "kind" | "name"> | undefined,
): string {
  if (!workspace || workspace.kind === "personal") return "Personal";
  return workspace.name;
}

/** Compact route context shown beside the brand in the mobile header. */
export function workspaceMobileContextLabel(
  pathname: string,
  workspace: Pick<Workspace, "kind" | "name"> | undefined,
): string {
  if (pathname === "/" || pathname === "/graphs") return "Graphs";
  if (pathname === "/templates/new") return "Save template";
  if (pathname.startsWith("/templates")) return "Templates";
  if (/^\/workspaces\/[^/]+\/settings\/?$/.test(pathname)) return "Settings";
  if (pathname === "/workspaces" || /^\/workspaces\/[^/]+\/?$/.test(pathname)) {
    return "Teams & access";
  }
  if (/^\/workspaces\/[^/]+\/graphs(?:\/|$)/.test(pathname)) {
    return workspaceSelectorLabel(workspace);
  }
  return "Graphs";
}

/** The workspace the switcher should present, defaulting to the personal one. */
export function resolveSelectedWorkspace(
  workspaces: readonly Workspace[] | undefined,
  activeSlug: string | undefined,
): Workspace | undefined {
  if (activeSlug) {
    const active = workspaces?.find(
      (candidate) => candidate.slug === activeSlug,
    );
    if (active) return active;
  }
  return workspaces?.find((candidate) => candidate.kind === "personal");
}

export function sessionDisplayName(
  session: Pick<Session, "display_name" | "email" | "user_id">,
): string {
  const named = session.display_name?.trim();
  if (named) return named;
  const email = session.email?.trim();
  if (email) return email.split("@")[0] || email;
  return "User";
}

export function sessionInitials(
  session: Pick<Session, "display_name" | "email" | "user_id">,
): string {
  const named = session.display_name?.trim();
  if (named) {
    const parts = named.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0]![0] ?? ""}${parts[1]![0] ?? ""}`.toUpperCase();
    }
    return named.slice(0, 2).toUpperCase();
  }
  const email = session.email?.trim();
  if (email) return email.slice(0, 2).toUpperCase();
  return session.user_id.slice(0, 2).toUpperCase();
}

const WorkspaceContext = React.createContext<WorkspaceContextValue | null>(
  null,
);

export function useWorkspaceContext(): WorkspaceContextValue {
  const context = React.useContext(WorkspaceContext);
  if (!context)
    throw new Error(
      "useWorkspaceContext must be used inside a workspace route",
    );
  return context;
}

/**
 * The same value, for a surface that must render without a workspace route.
 * A sandbox exercises real node bodies with a stand-in workspace, and the
 * popover degrades instead of throwing. Product routes keep using
 * {@link useWorkspaceContext}, which still throws on a missing provider.
 */
export function useOptionalWorkspaceContext(): WorkspaceContextValue | null {
  return React.useContext(WorkspaceContext);
}

export function WorkspaceContextScope({
  value,
  children,
}: {
  value: WorkspaceContextValue;
  children: React.ReactNode;
}) {
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function WorkspaceRail({
  workspaces,
  activeSlug,
  session,
  onLogout,
  onBrandClick,
  onNewGraph,
}: {
  workspaces: readonly Workspace[];
  activeSlug?: string;
  session: Session;
  onLogout: () => Promise<void>;
  /** Optional graph-browser behavior when creation may require a location choice. */
  onNewGraph?: () => void;
  /** Optional same-page behavior for the brand button. */
  onBrandClick?: () => void;
}) {
  const router = useRouter();
  const { mutate: mutateCache } = useSWRConfig();
  const pathname = usePathname() ?? "";
  const { cycleTheme, preference } = useTheme();
  const [collapsed, setCollapsed] = useRailCollapsed();
  const mobileViewport = useMediaQuery(RAIL_MOBILE_QUERY);
  const [accountMenuPath, setAccountMenuPath] = React.useState<string | null>(
    null,
  );
  const [mobileNavigationPath, setMobileNavigationPath] = React.useState<
    string | null
  >(null);
  const [graphActionBusyId, setGraphActionBusyId] = React.useState<
    string | null
  >(null);
  const [previewCollapsed, setPreviewCollapsed] = React.useState<
    boolean | null
  >(null);
  const {
    data: workspaceInvitations,
    error: invitationError,
    mutate: mutateInvitations,
  } = useMyWorkspaceInvitations(session.user_id);
  const [invitationDialogOpen, setInvitationDialogOpen] = React.useState(false);
  const [invitationBusyId, setInvitationBusyId] = React.useState<string | null>(
    null,
  );
  const [invitationMessage, setInvitationMessage] = React.useState<
    string | null
  >(null);
  const mobileMenuButtonRef = React.useRef<HTMLButtonElement>(null);
  const mobileRailRef = React.useRef<HTMLElement>(null);
  const chrome = useWorkbenchChrome();
  const dragRef = React.useRef<{
    pointerId: number;
    startX: number;
    startWidth: number;
    moved: boolean;
  } | null>(null);

  const accountMenuOpen = accountMenuPath === pathname;
  const mobileOpen = mobileNavigationPath === pathname;

  const clearOverlayState = React.useCallback(() => {
    setAccountMenuPath(null);
    setMobileNavigationPath(null);
  }, []);

  React.useEffect(() => {
    // Visibility is already scoped to pathname; this clears obsolete tokens so
    // Back/Forward cannot make them current again.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    clearOverlayState();
  }, [clearOverlayState, pathname]);

  const closeMobileNavigation = React.useCallback(
    (restoreFocus = false) => {
      clearOverlayState();
      if (!restoreFocus) return;
      window.requestAnimationFrame(() => mobileMenuButtonRef.current?.focus());
    },
    [clearOverlayState],
  );

  const selectedWorkspace = resolveSelectedWorkspace(workspaces, activeSlug);
  const activeWorkspace = activeSlug
    ? workspaces.find((candidate) => candidate.slug === activeSlug)
    : undefined;

  const goGraphs = () => {
    closeMobileNavigation(true);
    if (!selectedWorkspace) {
      router.push("/workspaces");
      return;
    }
    router.push(
      `/workspaces/${encodeURIComponent(selectedWorkspace.slug)}/graphs`,
    );
  };

  const activateBrand = () => {
    if (onBrandClick) {
      closeMobileNavigation(true);
      onBrandClick();
    } else {
      goGraphs();
    }
  };

  const onChangeWorkspace = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const slug = event.currentTarget.value;
    if (!slug) return;
    closeMobileNavigation(true);
    const suffix = /^\/workspaces\/[^/]+\/settings\/?$/.test(pathname)
      ? "/settings"
      : "/graphs";
    router.push(`/workspaces/${encodeURIComponent(slug)}${suffix}`);
  };

  const acceptInvitation = async (invitationId: string) => {
    setInvitationBusyId(invitationId);
    setInvitationMessage(null);
    try {
      const acceptedWorkspace = await acceptWorkspaceInvitation(invitationId);
      await mutateInvitations();
      await mutateCache(["workspaces", session.user_id]);
      setInvitationDialogOpen(false);
      router.push(`/workspaces/${encodeURIComponent(acceptedWorkspace.slug)}`);
    } catch {
      setInvitationMessage(
        "The invitation could not be accepted. It may have expired or changed.",
      );
    } finally {
      setInvitationBusyId(null);
    }
  };

  const declineInvitation = async (invitationId: string) => {
    setInvitationBusyId(invitationId);
    setInvitationMessage(null);
    try {
      await declineWorkspaceInvitation(invitationId);
      await mutateInvitations();
      setInvitationMessage("Invitation declined.");
    } catch {
      setInvitationMessage(
        "The invitation could not be declined. It may have expired or changed.",
      );
    } finally {
      setInvitationBusyId(null);
    }
  };

  const finishResize = React.useCallback(
    (clientX: number) => {
      const drag = dragRef.current;
      if (!drag) return;
      const nextWidth = Math.min(
        RAIL_EXPANDED_WIDTH,
        Math.max(
          RAIL_COLLAPSED_WIDTH,
          drag.startWidth + (clientX - drag.startX),
        ),
      );
      const wasClick = !drag.moved;
      const nextCollapsed = wasClick
        ? !collapsed
        : nextWidth < RAIL_COLLAPSE_THRESHOLD;
      dragRef.current = null;
      setPreviewCollapsed(null);
      setCollapsed(nextCollapsed);
      clearRailWidthOverride();
    },
    [collapsed, setCollapsed],
  );

  const onResizePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    if (!window.matchMedia(RAIL_DESKTOP_QUERY).matches) return;
    event.preventDefault();
    const startWidth = collapsed ? RAIL_COLLAPSED_WIDTH : RAIL_EXPANDED_WIDTH;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setPreviewCollapsed(collapsed);
    setRailWidthOverride(startWidth);
  };

  const onResizePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.startX;
    if (!drag.moved && Math.abs(deltaX) >= 4) {
      drag.moved = true;
    }
    if (!drag.moved) return;
    const nextWidth = Math.min(
      RAIL_EXPANDED_WIDTH,
      Math.max(RAIL_COLLAPSED_WIDTH, drag.startWidth + deltaX),
    );
    setRailWidthOverride(nextWidth);
    setPreviewCollapsed(nextWidth < RAIL_COLLAPSE_THRESHOLD);
  };

  const onResizePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    finishResize(event.clientX);
  };

  React.useEffect(() => () => clearRailWidthOverride(), []);

  const previousMobileViewportRef = React.useRef(mobileViewport);
  React.useEffect(() => {
    const previousMobileViewport = previousMobileViewportRef.current;
    previousMobileViewportRef.current = mobileViewport;
    if (previousMobileViewport === mobileViewport) return;

    const focusWasInsideRail = mobileRailRef.current?.contains(
      document.activeElement,
    );
    setMobileNavigationPath(null);
    setAccountMenuPath(null);
    if (!focusWasInsideRail) return;

    window.requestAnimationFrame(() => {
      if (mobileViewport) {
        mobileMenuButtonRef.current?.focus();
        return;
      }
      mobileRailRef.current
        ?.querySelector<HTMLElement>("[aria-label='Switch workspace']")
        ?.focus();
    });
  }, [mobileViewport]);

  React.useEffect(() => {
    if (!mobileViewport || !mobileOpen) return;
    const rail = mobileRailRef.current;
    if (!rail) return;
    const focusableSelectors = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ];
    const focusableSelector = focusableSelectors.join(",");
    const visibleFocusableElements = () =>
      [...rail.querySelectorAll<HTMLElement>(focusableSelector)].filter(
        (element) =>
          element.getAttribute("aria-hidden") !== "true" &&
          element.getClientRects().length > 0,
      );
    const focusFrame = window.requestAnimationFrame(() => {
      visibleFocusableElements()[0]?.focus();
    });
    const containFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMobileNavigation(true);
        return;
      }
      if (event.key !== "Tab") return;
      const focusableElements = visibleFocusableElements();
      if (!focusableElements.length) return;
      const first = focusableElements[0]!;
      const last = focusableElements[focusableElements.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey) {
        if (
          active !== first &&
          focusableElements.includes(active as HTMLElement)
        ) {
          return;
        }
        event.preventDefault();
        last.focus();
        return;
      }
      if (
        active !== last &&
        focusableElements.includes(active as HTMLElement)
      ) {
        return;
      }
      event.preventDefault();
      first.focus();
    };
    document.addEventListener("keydown", containFocus);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", containFocus);
    };
  }, [closeMobileNavigation, mobileOpen, mobileViewport]);

  const themeLabel =
    preference === "light"
      ? "Light theme"
      : preference === "dark"
        ? "Dark theme"
        : "System theme";
  const displayName = sessionDisplayName(session);
  const initials = sessionInitials(session);
  const email = session.email?.trim() || null;
  const visuallyCollapsed = previewCollapsed ?? collapsed;
  const mobileNavigationHidden = mobileViewport && !mobileOpen;
  const graphBrowserActive = Boolean(
    activeSlug &&
    (pathname === `/workspaces/${encodeURIComponent(activeSlug)}/graphs` ||
      pathname === `/workspaces/${encodeURIComponent(activeSlug)}/graphs/`),
  );
  const workspaceSettingsActive = Boolean(
    activeSlug &&
    pathname === `/workspaces/${encodeURIComponent(activeSlug)}/settings`,
  );
  const mobileContextLabel = workspaceMobileContextLabel(
    pathname,
    selectedWorkspace,
  );
  const activeGraphId = workspaceRouteGraphId(pathname);
  const { data: savedGraphs } = useSavedGraphs(
    activeWorkspace?.id,
  );
  const refreshGraphSummaries = useGraphSummaryRefresh();
  const recentGraphs = React.useMemo(
    () =>
      sortGraphsByRecency(savedGraphs?.graphs ?? []).slice(
        0,
        RAIL_RECENT_GRAPH_LIMIT,
      ),
    [savedGraphs],
  );

  const renameGraph = React.useCallback(
    async (graph: SavedGraphSummary) => {
      if (!activeWorkspace) return;
      const next = promptGraphRename(graph.name);
      if (!next) return;
      setGraphActionBusyId(graph.id);
      try {
        if (chrome) {
          await chrome.renameGraph(graph, next);
        } else {
          await renameSavedGraphRemote(activeWorkspace.id, graph, next);
        }
        void refreshGraphSummaries(activeWorkspace.id);
      } catch (error) {
        window.alert(
          error instanceof Error
            ? error.message
            : "The graph could not be renamed.",
        );
      } finally {
        setGraphActionBusyId(null);
      }
    },
    [activeWorkspace, chrome, refreshGraphSummaries],
  );

  const deleteGraph = React.useCallback(
    async (graph: SavedGraphSummary) => {
      if (!activeWorkspace) return;
      setGraphActionBusyId(graph.id);
      try {
        if (chrome) {
          await chrome.deleteGraph(graph);
        } else {
          const deleted = await deleteSavedGraphRemote(
            activeWorkspace.id,
            graph,
          );
          if (!deleted) return;
        }
        void refreshGraphSummaries(activeWorkspace.id);
      } catch (error) {
        window.alert(
          error instanceof Error
            ? error.message
            : "The graph could not be deleted.",
        );
      } finally {
        setGraphActionBusyId(null);
      }
    },
    [activeWorkspace, chrome, refreshGraphSummaries],
  );

  return (
    <>
      <header className="grafy-mobile-nav">
        <button
          ref={mobileMenuButtonRef}
          type="button"
          className="grafy-mobile-nav__menu"
          aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
          aria-controls="grafy-primary-navigation"
          aria-expanded={mobileOpen}
          onClick={() => {
            if (mobileOpen) {
              closeMobileNavigation(true);
            } else {
              setAccountMenuPath(null);
              setMobileNavigationPath(pathname);
            }
          }}
        >
          {mobileOpen ? (
            <X size={20} aria-hidden="true" />
          ) : (
            <Menu size={20} aria-hidden="true" />
          )}
        </button>
        <button
          type="button"
          className="grafy-mobile-nav__brand"
          aria-label="Graphs"
          onClick={activateBrand}
        >
          <BrandWordmark height={22} />
        </button>
        <span className="grafy-mobile-nav__location">{mobileContextLabel}</span>
      </header>

      <div
        className={`grafy-mobile-nav__backdrop${mobileOpen ? " is-open" : ""}`}
        aria-hidden="true"
        onClick={() => closeMobileNavigation(true)}
      />

      <aside
        ref={mobileRailRef}
        id="grafy-primary-navigation"
        className={`grafy-workspace-rail${visuallyCollapsed ? " is-collapsed" : ""}${mobileOpen ? " is-mobile-open" : ""}`}
        role={mobileViewport && mobileOpen ? "dialog" : undefined}
        aria-modal={mobileViewport && mobileOpen ? true : undefined}
        aria-hidden={mobileNavigationHidden ? true : undefined}
        inert={mobileNavigationHidden ? true : undefined}
        aria-label="Primary navigation"
      >
        <button
          type="button"
          className="grafy-workspace-rail__item grafy-workspace-rail__mobile-close"
          onClick={() => closeMobileNavigation(true)}
        >
          <span>Close navigation</span>
          <X size={18} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="grafy-workspace-rail__brand"
          aria-label="Graphs"
          onClick={activateBrand}
        >
          <BrandWordmark
            className="grafy-workspace-rail__brand-wordmark"
            height={24}
          />
          <BrandIcon
            className="grafy-workspace-rail__brand-icon"
            size={28}
            alt=""
          />
        </button>

        <nav className="grafy-workspace-rail__nav" aria-label="Workspaces">
          <p className="grafy-workspace-rail__section-label">Workspaces</p>
          <label className="grafy-workspace-rail__workspace-select">
            <span
              className="grafy-workspace-rail__workspace-select-icon"
              aria-hidden="true"
            >
              {selectedWorkspace?.kind === "personal" ? (
                <Workflow size={15} />
              ) : (
                <Users size={15} />
              )}
            </span>
            <select
              value={selectedWorkspace?.slug ?? ""}
              aria-label="Switch workspace"
              title={workspaceSelectorLabel(selectedWorkspace)}
              onChange={onChangeWorkspace}
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.slug}>
                  {workspaceSelectorLabel(workspace)}
                </option>
              ))}
            </select>
            <span
              className="grafy-workspace-rail__workspace-select-chevron"
              aria-hidden="true"
            >
              <ChevronsUpDown size={12} />
            </span>
          </label>
          <button
            type="button"
            className="grafy-workspace-rail__item"
            title="Workspace invitations"
            aria-label={`Workspace invitations${workspaceInvitations?.length ? `, ${workspaceInvitations.length} pending` : ""}`}
            onClick={() => {
              setInvitationMessage(null);
              setInvitationDialogOpen(true);
            }}
          >
            <Mail size={15} aria-hidden="true" />
            <span>Invitations</span>
            {workspaceInvitations?.length ? (
              <span className="grafy-workspace-rail__badge">
                {workspaceInvitations.length}
              </span>
            ) : null}
          </button>
        </nav>

        <Dialog
          open={invitationDialogOpen}
          onOpenChange={setInvitationDialogOpen}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Workspace invitations</DialogTitle>
              <DialogDescription>
                Review invitations before joining a shared workspace.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              {invitationError ? (
                <p className="grafy-member-message" role="status">
                  Invitations could not be loaded.
                </p>
              ) : null}
              {!workspaceInvitations ? (
                <p className="grafy-member-empty">Loading invitations…</p>
              ) : workspaceInvitations.length === 0 ? (
                <p className="grafy-member-empty">
                  You have no pending invitations.
                </p>
              ) : (
                <div className="grafy-member-list">
                  {workspaceInvitations.map((invitation) => (
                    <div
                      className="grafy-invitation-recipient"
                      key={invitation.id}
                    >
                      <div>
                        <strong>{invitation.workspace.name}</strong>
                        <span>
                          Invited by{" "}
                          {invitation.invited_by.display_name ??
                            invitation.invited_by.email ??
                            "a workspace owner"}{" "}
                          · {invitation.role} · expires{" "}
                          {new Date(invitation.expires_at).toLocaleDateString()}
                        </span>
                      </div>
                      <p>{roleDescriptionsForInvitation[invitation.role]}</p>
                      <div>
                        <button
                          type="button"
                          className="grafy-workspace-button"
                          disabled={invitationBusyId === invitation.id}
                          onClick={() => void declineInvitation(invitation.id)}
                        >
                          Decline
                        </button>
                        <button
                          type="button"
                          className="grafy-workspace-button grafy-workspace-button--primary"
                          disabled={invitationBusyId === invitation.id}
                          onClick={() => void acceptInvitation(invitation.id)}
                        >
                          Accept
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {invitationMessage ? (
                <p className="grafy-member-message" role="status">
                  {invitationMessage}
                </p>
              ) : null}
            </DialogBody>
          </DialogContent>
        </Dialog>

        <nav className="grafy-workspace-rail__nav" aria-label="Graphs">
          <p className="grafy-workspace-rail__section-label">Graphs</p>
          <button
            type="button"
            className={`grafy-workspace-rail__item${graphBrowserActive ? " is-active" : ""}`}
            title="Browse all graphs"
            onClick={goGraphs}
          >
            <Workflow size={15} aria-hidden="true" />
            <span>All graphs</span>
          </button>
          {activeWorkspace || onNewGraph ? (
            <button
              type="button"
              className="grafy-workspace-rail__item"
              title="New graph"
              onClick={() => {
                closeMobileNavigation(true);
                if (onNewGraph) {
                  onNewGraph();
                  return;
                }
                if (activeWorkspace) {
                  router.push(
                    workbenchGraphPath(
                      activeWorkspace.slug,
                      NEW_GRAPH_ROUTE_ID,
                    ),
                  );
                }
              }}
            >
              <Plus size={15} aria-hidden="true" />
              <span>New graph</span>
            </button>
          ) : null}
          {activeWorkspace && chrome ? (
            <button
              type="button"
              className={`grafy-workspace-rail__item${chrome.isDirty ? " is-active" : ""}`}
              title={
                chrome.saving
                  ? "Saving graph…"
                  : chrome.isDirty || !chrome.activeGraphId
                    ? "Save graph"
                    : "All changes are saved"
              }
              disabled={!chrome.canSave}
              onClick={() => void chrome.save()}
            >
              {chrome.saving ? (
                <LoaderCircle
                  size={15}
                  aria-hidden="true"
                  className="grafy-workspace-rail__spin"
                />
              ) : (
                <Save size={15} aria-hidden="true" />
              )}
              <span>
                {chrome.saving
                  ? "Saving…"
                  : chrome.isDirty || !chrome.activeGraphId
                    ? "Save"
                    : "Saved"}
              </span>
            </button>
          ) : null}
        </nav>

        {activeWorkspace && !visuallyCollapsed && recentGraphs.length ? (
          <nav
            className="grafy-workspace-rail__nav grafy-workspace-rail__nav--open"
            aria-label="Recent graphs"
          >
            <p className="grafy-workspace-rail__section-label">Recent</p>
            <div className="grafy-workspace-rail__items">
              {recentGraphs.map((graph) => (
                <div
                  key={graph.id}
                  className={`grafy-graph-row${activeGraphId === graph.id ? " is-active" : ""}`}
                >
                  <button
                    type="button"
                    className="grafy-workspace-rail__item grafy-graph-row__open"
                    title={graph.name}
                    aria-label={graph.name}
                    onClick={() => {
                      closeMobileNavigation(false);
                      router.push(
                        workbenchGraphPath(activeWorkspace.slug, graph.id),
                      );
                    }}
                  >
                    <span>{graph.name}</span>
                  </button>
                  <GraphRowMenu
                    graph={graph}
                    busy={graphActionBusyId === graph.id}
                    onRename={(entry) => void renameGraph(entry)}
                    onDelete={(entry) => void deleteGraph(entry)}
                  />
                </div>
              ))}
            </div>
          </nav>
        ) : null}

        <button
          type="button"
          className={`grafy-workspace-rail__settings${workspaceSettingsActive ? " is-active" : ""}`}
          onClick={() => {
            closeMobileNavigation(true);
            if (selectedWorkspace) {
              router.push(
                `/workspaces/${encodeURIComponent(selectedWorkspace.slug)}/settings`,
              );
            }
          }}
          title="Settings"
          disabled={!selectedWorkspace}
        >
          <Settings size={15} aria-hidden="true" />
          <span>Settings</span>
        </button>

        <div className="grafy-workspace-rail__footer">
          <Popover.Root
            open={accountMenuOpen}
            onOpenChange={(open) => {
              setAccountMenuPath(open ? pathname : null);
            }}
          >
            <Popover.Trigger
              className="grafy-workspace-rail__account"
              title={displayName}
              aria-label="Account menu"
            >
              <span className="grafy-workspace-rail__avatar" aria-hidden="true">
                {initials}
              </span>
              <span className="grafy-workspace-rail__account-copy">
                <span className="grafy-workspace-rail__account-name">
                  {displayName}
                </span>
                {email ? (
                  <span className="grafy-workspace-rail__account-email">
                    {email}
                  </span>
                ) : null}
              </span>
            </Popover.Trigger>
            <Popover.Portal container={mobileViewport ? mobileRailRef : null}>
              <Popover.Positioner
                className="grafy-workspace-rail__account-positioner"
                side="top"
                align="start"
                sideOffset={8}
              >
                <Popover.Popup className="grafy-workspace-rail__account-menu">
                  <button
                    type="button"
                    className="grafy-workspace-rail__account-menu-item"
                    onClick={() => {
                      cycleTheme();
                      setAccountMenuPath(null);
                    }}
                  >
                    <Settings size={14} aria-hidden="true" />
                    {themeLabel}
                  </button>
                  <button
                    type="button"
                    className="grafy-workspace-rail__account-menu-item"
                    onClick={() => {
                      setAccountMenuPath(null);
                      void onLogout();
                    }}
                  >
                    <LogOut size={14} aria-hidden="true" />
                    Log out
                  </button>
                </Popover.Popup>
              </Popover.Positioner>
            </Popover.Portal>
          </Popover.Root>
        </div>

        <div
          className="grafy-workspace-rail__resize"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          aria-valuemin={RAIL_COLLAPSED_WIDTH}
          aria-valuemax={RAIL_EXPANDED_WIDTH}
          aria-valuenow={collapsed ? RAIL_COLLAPSED_WIDTH : RAIL_EXPANDED_WIDTH}
          title="Click to collapse or expand · drag to resize"
          onPointerDown={onResizePointerDown}
          onPointerMove={onResizePointerMove}
          onPointerUp={onResizePointerUp}
          onPointerCancel={onResizePointerUp}
        />
      </aside>
    </>
  );
}

function WorkspaceRouteStatus({
  title,
  detail,
  loading = false,
}: {
  title: string;
  detail: string;
  loading?: boolean;
}) {
  return (
    <ThresholdStatus
      title={title}
      detail={detail}
      loading={loading}
      action={
        loading ? undefined : <Link href="/graphs">Return to graphs</Link>
      }
    />
  );
}

export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();
  const { session, logout } = useAuthSession();
  const { data, error, mutate } = useWorkspaces(session.user_id);
  const [previouslyResolvedWorkspace, setPreviouslyResolvedWorkspace] =
    React.useState<Pick<Workspace, "slug" | "id"> | undefined>(undefined);

  const workspace = data?.find((candidate) => candidate.slug === workspaceSlug);
  if (
    workspace &&
    (previouslyResolvedWorkspace?.slug !== workspace.slug ||
      previouslyResolvedWorkspace.id !== workspace.id)
  ) {
    setPreviouslyResolvedWorkspace({ slug: workspace.slug, id: workspace.id });
  }
  const routeAccessState = workspaceRouteAccessState(
    workspaceSlug,
    workspace,
    previouslyResolvedWorkspace,
  );

  if (error) {
    return (
      <WorkspaceRouteStatus
        title="Graph location unavailable"
        detail="Grafy could not confirm access to this graph location."
      />
    );
  }
  if (!data) {
    return (
      <WorkspaceRouteStatus
        title="Loading graph location"
        detail="Checking your current access…"
        loading
      />
    );
  }

  if (!workspace) {
    return routeAccessState === "revoked" ? (
      <WorkspaceRouteStatus
        title="Graph location access removed"
        detail="Your access to this location is no longer available."
      />
    ) : (
      <WorkspaceRouteStatus
        title="Graph location not found"
        detail="This graph location is not available to your account."
      />
    );
  }

  return (
    <WorkspaceContext.Provider
      value={{
        workspace,
        workspaces: data,
        refreshWorkspaces: () => mutate(),
      }}
    >
      <div className="grafy-workspace-frame">
        <WorkspaceRail
          workspaces={data}
          activeSlug={workspace.slug}
          session={session}
          onLogout={logout}
        />
        <div className="grafy-workspace-frame__main">{children}</div>
      </div>
    </WorkspaceContext.Provider>
  );
}
