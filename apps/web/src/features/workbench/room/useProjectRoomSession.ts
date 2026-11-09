"use client";

import * as React from "react";

import type {
  ActiveRunSummary,
  CollaborativeHead,
  WorkspaceCapability,
} from "@/lib/api";

import {
  ProjectRoomSession,
  type ProjectRoomAcceptedMeta,
  type ProjectRoomFailure,
  type ProjectRoomStatus,
  type ProjectRoomTerminalReason,
  type PresenceParticipant,
  type PresenceUpdateSubmit,
  type RoomInstanceState,
  type RoomProjectCommand,
} from "./graph-room-session";
import { instanceKeyText } from "./protocol";
import type {
  InstancesChangedMessage,
  ProjectCommandAcceptedMessage,
  ProjectCommandRejectedMessage,
  RoomReadyMessage,
  RunFinishedMessage,
} from "./protocol";

export interface ProjectRoomSubmitResult {
  readonly receipt: Awaited<
    ReturnType<ProjectRoomSession["submitCommands"]>
  >["receipt"];
  readonly accepted: Awaited<
    ReturnType<ProjectRoomSession["submitCommands"]>
  >["accepted"];
  readonly head: CollaborativeHead;
}

export interface UseProjectRoomSessionResult {
  readonly status: ProjectRoomStatus;
  readonly terminalReason: ProjectRoomTerminalReason | null;
  readonly failure: ProjectRoomFailure | null;
  readonly head: CollaborativeHead | null;
  /** What the room says this caller may do, in the API's own words — the type
   * is the point: a made-up capability name must not compile. */
  readonly capabilities: readonly WorkspaceCapability[];
  readonly authorizationVersion: number | null;
  readonly canSubmitCommands: boolean;
  readonly canPublishPresence: boolean;
  readonly canRun: boolean;
  readonly localSessionId: string | null;
  readonly participants: readonly PresenceParticipant[];
  /**
   * Every Run the room believes is open for this Project. **No order is
   * promised**: the join snapshot arrives `created_at DESC` while a locally
   * observed `run.started` appends, so a consumer that wants the newest Run must
   * sort on `created_at` rather than read the end of the list.
   */
  readonly activeRuns: readonly ActiveRunSummary[];
  /** Bumped on every room push of active Runs: `room.ready`, `run.started`, `run.finished`. */
  readonly runsRevision: number;
  /** Instance states the room carried in, keyed by instance key text. */
  readonly instances: ReadonlyMap<string, RoomInstanceState>;
  /** Bumped on `instances.changed`, the room's only signal that a result landed. */
  readonly instancesRevision: number;
  readonly submitCommands: (
    commands: readonly RoomProjectCommand[],
  ) => Promise<ProjectRoomSubmitResult>;
  /** Reconcile a full snapshot and return the effective room head. */
  readonly replaceHead: (head: CollaborativeHead) => CollaborativeHead;
  /** Reconcile a checkpoint only within the epoch of its submitted command. */
  readonly reconcileCheckpointHead: (
    head: CollaborativeHead,
    expectedRoomEpoch: string,
  ) => CollaborativeHead;
  readonly publishPresence: (
    update: Omit<PresenceUpdateSubmit, "presence_sequence">,
  ) => boolean;
  readonly retry: () => void;
}

interface UseProjectRoomSessionOptions {
  workspaceId: string;
  projectId: string | null;
  onReady?: (ready: RoomReadyMessage) => void;
  onRehydrate?: (head: CollaborativeHead) => void;
  onHeadRefreshRequired?: () => void;
  onCommandAccepted?: (
    message: ProjectCommandAcceptedMessage,
    meta: ProjectRoomAcceptedMeta,
  ) => void;
  onCommandRejected?: (message: ProjectCommandRejectedMessage) => void;
  onActiveRunsChange?: (runs: readonly ActiveRunSummary[]) => void;
  onRunFinished?: (message: RunFinishedMessage) => void;
  onInstancesChange?: (message: InstancesChangedMessage) => void;
  onTerminalClose?: (reason: ProjectRoomTerminalReason) => void;
}

const EMPTY_RUNS: readonly ActiveRunSummary[] = [];
const EMPTY_INSTANCES: ReadonlyMap<string, RoomInstanceState> = new Map();

export function useProjectRoomSession({
  workspaceId,
  projectId,
  onReady,
  onRehydrate,
  onHeadRefreshRequired,
  onCommandAccepted,
  onCommandRejected,
  onActiveRunsChange,
  onRunFinished,
  onInstancesChange,
  onTerminalClose,
}: UseProjectRoomSessionOptions): UseProjectRoomSessionResult {
  const [stateProjectId, setStateProjectId] = React.useState<string | null>(
    null,
  );
  const [status, setStatus] = React.useState<ProjectRoomStatus>("idle");
  const [terminalReason, setTerminalReason] =
    React.useState<ProjectRoomTerminalReason | null>(null);
  const [failure, setFailure] = React.useState<ProjectRoomFailure | null>(null);
  const [head, setHead] = React.useState<CollaborativeHead | null>(null);
  const [capabilities, setCapabilities] = React.useState<
    readonly WorkspaceCapability[]
  >([]);
  const [authorizationVersion, setAuthorizationVersion] = React.useState<
    number | null
  >(null);
  const [participants, setParticipants] = React.useState<
    readonly PresenceParticipant[]
  >([]);
  const [activeRuns, setActiveRunsState] =
    React.useState<readonly ActiveRunSummary[]>(EMPTY_RUNS);
  const [instances, setInstancesState] =
    React.useState<ReadonlyMap<string, RoomInstanceState>>(EMPTY_INSTANCES);
  /**
   * Revisions, not snapshots. A listener needs to know the room pushed again, and
   * a list that happens to look identical still means "read the results again" —
   * so a counter travels beside the state instead of identity standing in for it.
   */
  const [runsRevision, setRunsRevision] = React.useState(0);
  const [instancesRevision, setInstancesRevision] = React.useState(0);
  const setActiveRuns = React.useCallback(
    (next: readonly ActiveRunSummary[]) => {
      setActiveRunsState(next);
      setRunsRevision((revision) => revision + 1);
    },
    [],
  );
  const setInstances = React.useCallback(
    (next: ReadonlyMap<string, RoomInstanceState>) => {
      setInstancesState(next);
      setInstancesRevision((revision) => revision + 1);
    },
    [],
  );
  const [localSessionId, setLocalSessionId] = React.useState<string | null>(
    null,
  );
  const sessionRef = React.useRef<ProjectRoomSession | null>(null);

  const onReadyRef = React.useRef(onReady);
  const onRehydrateRef = React.useRef(onRehydrate);
  const onHeadRefreshRequiredRef = React.useRef(onHeadRefreshRequired);
  const onCommandAcceptedRef = React.useRef(onCommandAccepted);
  const onCommandRejectedRef = React.useRef(onCommandRejected);
  const onActiveRunsChangeRef = React.useRef(onActiveRunsChange);
  const onRunFinishedRef = React.useRef(onRunFinished);
  const onInstancesChangeRef = React.useRef(onInstancesChange);
  const onTerminalCloseRef = React.useRef(onTerminalClose);

  React.useEffect(() => {
    onReadyRef.current = onReady;
    onRehydrateRef.current = onRehydrate;
    onHeadRefreshRequiredRef.current = onHeadRefreshRequired;
    onCommandAcceptedRef.current = onCommandAccepted;
    onCommandRejectedRef.current = onCommandRejected;
    onActiveRunsChangeRef.current = onActiveRunsChange;
    onRunFinishedRef.current = onRunFinished;
    onInstancesChangeRef.current = onInstancesChange;
    onTerminalCloseRef.current = onTerminalClose;
  }, [
    onCommandAccepted,
    onCommandRejected,
    onHeadRefreshRequired,
    onInstancesChange,
    onReady,
    onRehydrate,
    onRunFinished,
    onActiveRunsChange,
    onTerminalClose,
  ]);

  React.useEffect(() => {
    if (!projectId) {
      sessionRef.current?.disconnect();
      sessionRef.current = null;
      return;
    }

    const session = new ProjectRoomSession({
      workspaceId,
      projectId,
      onStatusChange: (nextStatus) => {
        setStateProjectId(projectId);
        setStatus(nextStatus);
        if (nextStatus === "connecting" || nextStatus === "reconnecting") {
          setTerminalReason(null);
        }
        if (nextStatus !== "connecting") return;
        setFailure(null);
        setHead(null);
        setCapabilities([]);
        setAuthorizationVersion(null);
        setParticipants([]);
        setActiveRuns(EMPTY_RUNS);
        setInstances(EMPTY_INSTANCES);
        setLocalSessionId(null);
      },
      onReady: (ready) => {
        setHead(ready.head);
        setCapabilities(ready.capabilities.capabilities);
        setAuthorizationVersion(ready.capabilities.authorization_version);
        setTerminalReason(null);
        setFailure(null);
        setLocalSessionId(ready.project_room_session_id);
        setParticipants(ready.participants);
        setActiveRuns(ready.active_runs);
        setInstances(instanceMap(ready.instances));
        onReadyRef.current?.(ready);
      },
      onRehydrate: (nextHead) => {
        setHead(nextHead);
        onRehydrateRef.current?.(nextHead);
      },
      onHeadRefreshRequired: () => {
        onHeadRefreshRequiredRef.current?.();
      },
      onCommandAccepted: (message, meta) => {
        const nextHead = session.getHead();
        if (nextHead) setHead(nextHead);
        onCommandAcceptedRef.current?.(message, meta);
      },
      onCommandRejected: (message) => {
        const nextHead = session.getHead();
        if (nextHead) setHead(nextHead);
        onCommandRejectedRef.current?.(message);
      },
      onPresenceChange: setParticipants,
      onFailureChange: (nextFailure) => {
        setFailure(nextFailure);
        if (!nextFailure) return;
        setCapabilities([]);
        setAuthorizationVersion(null);
        setParticipants([]);
        setActiveRuns(EMPTY_RUNS);
        setInstances(EMPTY_INSTANCES);
        setLocalSessionId(null);
      },
      onActiveRunsChange: (runs) => {
        setActiveRuns(runs);
        onActiveRunsChangeRef.current?.(runs);
      },
      onRunFinished: (message) => {
        setActiveRuns(session.getActiveRuns());
        onRunFinishedRef.current?.(message);
      },
      onInstancesChange: (message) => {
        // `changed` is a delta and `removed` was already applied inside the
        // session. Reading the session's own map is what keeps every other
        // node's state: taking the delta alone made the canvas forget which of
        // its nodes were fresh, one push at a time.
        setInstances(instanceMap(session.getInstances()));
        onInstancesChangeRef.current?.(message);
      },
      onTerminalClose: (reason) => {
        setTerminalReason(reason);
        setCapabilities([]);
        setAuthorizationVersion(null);
        setParticipants([]);
        setActiveRuns(EMPTY_RUNS);
        setInstances(EMPTY_INSTANCES);
        setLocalSessionId(null);
        onTerminalCloseRef.current?.(reason);
      },
    });
    sessionRef.current = session;
    session.connect();

    return () => {
      session.disconnect();
      if (sessionRef.current === session) {
        sessionRef.current = null;
      }
    };
  }, [projectId, setActiveRuns, setInstances, workspaceId]);

  const stateIsCurrent = projectId !== null && stateProjectId === projectId;
  const currentStatus = stateIsCurrent ? status : "idle";
  const currentTerminalReason = stateIsCurrent ? terminalReason : null;
  const currentFailure = stateIsCurrent ? failure : null;
  const currentHead = stateIsCurrent ? head : null;
  const currentCapabilities = stateIsCurrent ? capabilities : [];
  const currentAuthorizationVersion = stateIsCurrent
    ? authorizationVersion
    : null;
  const currentLocalSessionId = stateIsCurrent ? localSessionId : null;
  const currentParticipants = stateIsCurrent ? participants : [];
  const currentActiveRuns = stateIsCurrent ? activeRuns : EMPTY_RUNS;
  const currentInstances = stateIsCurrent ? instances : EMPTY_INSTANCES;

  const submitCommands = React.useCallback(
    async (
      commands: readonly RoomProjectCommand[],
    ): Promise<ProjectRoomSubmitResult> => {
      if (!projectId) {
        throw new Error("Project room is not connected.");
      }
      const session = sessionRef.current;
      if (!session) {
        throw new Error("Project room is not connected.");
      }
      const result = await session.submitCommands(commands);
      const nextHead = session.getHead();
      if (!nextHead) {
        throw new Error("Project room head is unavailable after submit.");
      }
      setHead(nextHead);
      return { ...result, head: nextHead };
    },
    [projectId],
  );

  const replaceHead = React.useCallback(
    (nextHead: CollaborativeHead) => {
      if (!projectId) {
        throw new Error("Project room is not connected.");
      }
      const session = sessionRef.current;
      if (!session) {
        throw new Error("Project room is not connected.");
      }
      session.replaceHead(nextHead);
      const effectiveHead = session.getHead();
      if (!effectiveHead) {
        throw new Error(
          "Project room head is unavailable after reconciliation.",
        );
      }
      setHead(effectiveHead);
      return effectiveHead;
    },
    [projectId],
  );

  const reconcileCheckpointHead = React.useCallback(
    (checkpointHead: CollaborativeHead, expectedRoomEpoch: string) => {
      if (!projectId) {
        throw new Error("Project room is not connected.");
      }
      const session = sessionRef.current;
      if (!session) {
        throw new Error("Project room is not connected.");
      }
      const effectiveHead = session.reconcileCheckpointHead(
        checkpointHead,
        expectedRoomEpoch,
      );
      setHead(effectiveHead);
      return effectiveHead;
    },
    [projectId],
  );

  const publishPresence = React.useCallback(
    (update: Omit<PresenceUpdateSubmit, "presence_sequence">): boolean => {
      if (!projectId) return false;
      return sessionRef.current?.publishPresence(update) ?? false;
    },
    [projectId],
  );

  const retry = React.useCallback(() => {
    if (!projectId) return;
    sessionRef.current?.retry();
  }, [projectId]);

  return {
    status: currentStatus,
    terminalReason: currentTerminalReason,
    failure: currentFailure,
    head: currentHead,
    capabilities: currentCapabilities,
    authorizationVersion: currentAuthorizationVersion,
    canSubmitCommands:
      currentStatus === "ready" &&
      currentHead !== null &&
      currentCapabilities.includes("edit_project") &&
      currentTerminalReason === null,
    canPublishPresence:
      currentStatus === "ready" &&
      currentCapabilities.includes("publish_presence") &&
      currentTerminalReason === null,
    canRun:
      currentStatus === "ready" &&
      // The API's capability for asking for work is start_run; there is no
      // run_project, so gating on that name left this permanently false.
      currentCapabilities.includes("start_run") &&
      currentTerminalReason === null,
    localSessionId: currentLocalSessionId,
    participants: currentParticipants,
    activeRuns: currentActiveRuns,
    instances: currentInstances,
    runsRevision,
    instancesRevision,
    submitCommands,
    replaceHead,
    reconcileCheckpointHead,
    publishPresence,
    retry,
  };
}

/**
 * Instance state keyed by its identity. A result belongs to a node instance, so
 * the canvas looks state up by the instance it is drawing, never by a Run.
 */
function instanceMap(
  entries: Iterable<RoomInstanceState>,
): ReadonlyMap<string, RoomInstanceState> {
  const next = new Map<string, RoomInstanceState>();
  for (const state of entries) {
    next.set(instanceKeyText(state), state);
  }
  return next;
}
