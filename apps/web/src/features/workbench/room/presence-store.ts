import { actorColor } from "./remote-selection";
import type {
  PresenceActivityKind,
  PresenceParticipant,
  PresencePoint,
  TransientNodePosition,
} from "./protocol";

const EMPTY_PARTICIPANTS: readonly PresenceParticipant[] = [];
const EMPTY_COLLABORATORS: readonly PresenceCollaborator[] = [];
const EMPTY_CURSOR_SAMPLES: readonly PresenceCursorSample[] = [];
const EMPTY_SELECTION_COLORS: ReadonlyMap<string, string> = new Map();
const EMPTY_DRAG_TARGETS: ReadonlyMap<string, TransientNodePosition> =
  new Map();

export interface PresenceCollaborator {
  readonly sessionId: string;
  readonly actorId: string;
  readonly displayName: string;
  readonly color: string;
  readonly activity: PresenceActivityKind | null;
  readonly activityTargetIds: readonly string[];
}

export interface PresenceCursorSample {
  readonly sessionId: string;
  readonly actorId: string;
  readonly displayName: string;
  readonly color: string;
  readonly cursor: PresencePoint;
  /** Changes for every arriving cursor-bearing frame, even at equal coordinates. */
  readonly sampleRevision: number;
}

interface ProjectionCache<T> {
  readonly revision: number;
  readonly snapshot: T;
}

type PresenceStoreListener = () => void;

interface PresenceStoreScope {
  readonly workspaceId: string;
  readonly projectId: string | null;
}

/**
 * One room session's presence. The wire snapshot stays here; React consumers
 * subscribe to cached, graph-scoped projections instead of waking the room owner.
 */
export class ProjectRoomPresenceStore {
  private participants = new Map<string, PresenceParticipant>();
  private localSessionId: string | null = null;
  private visualParticipants: readonly PresenceParticipant[] =
    EMPTY_PARTICIPANTS;
  private revision = 0;
  private cursorSampleRevision = 0;
  private readonly cursorRevisions = new Map<string, number>();
  private readonly listeners = new Set<PresenceStoreListener>();
  private readonly collaboratorCache = new Map<
    string,
    ProjectionCache<readonly PresenceCollaborator[]>
  >();
  private readonly cursorCache = new Map<
    string,
    ProjectionCache<readonly PresenceCursorSample[]>
  >();
  private readonly selectionCache = new Map<
    string,
    ProjectionCache<ReadonlyMap<string, string>>
  >();
  private readonly dragCache = new Map<
    string,
    ProjectionCache<ReadonlyMap<string, TransientNodePosition>>
  >();

  readonly scope: PresenceStoreScope | null;

  constructor(scope: PresenceStoreScope | null = null) {
    this.scope = scope;
  }

  readonly subscribe = (listener: PresenceStoreListener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getParticipants(): readonly PresenceParticipant[] {
    return this.visualParticipants;
  }

  replaceParticipants(
    participants: readonly PresenceParticipant[],
    localSessionId: string,
  ): void {
    this.participants = new Map(
      participants.map((participant) => [
        participant.project_room_session_id,
        participant,
      ]),
    );
    this.localSessionId = localSessionId;
    this.cursorRevisions.clear();
    for (const participant of participants) {
      this.recordCursorArrival(participant);
    }
    this.publishChange();
  }

  upsertParticipant(participant: PresenceParticipant): void {
    this.participants.set(participant.project_room_session_id, participant);
    this.recordCursorArrival(participant);
    this.publishChange();
  }

  removeParticipant(sessionId: string): boolean {
    if (!this.participants.delete(sessionId)) return false;
    this.cursorRevisions.delete(sessionId);
    this.publishChange();
    return true;
  }

  clear(): boolean {
    if (this.participants.size === 0 && this.localSessionId === null) {
      return false;
    }
    this.participants.clear();
    this.cursorRevisions.clear();
    this.localSessionId = null;
    this.publishChange();
    return true;
  }

  getCollaborators(graphId: string | null): readonly PresenceCollaborator[] {
    if (graphId === null) return EMPTY_COLLABORATORS;
    const cached = this.collaboratorCache.get(graphId);
    if (cached?.revision === this.revision) return cached.snapshot;

    const next: PresenceCollaborator[] = [];
    for (const participant of this.remoteParticipantsOnGraph(graphId)) {
      next.push({
        sessionId: participant.project_room_session_id,
        actorId: participant.actor.actor_id,
        displayName: participant.actor.display_name,
        color: actorColor(participant.actor.color),
        activity: participant.activity,
        activityTargetIds: participant.activity_target_ids,
      });
    }
    const snapshot =
      cached && sameCollaborators(cached.snapshot, next)
        ? cached.snapshot
        : next;
    this.collaboratorCache.set(graphId, {
      revision: this.revision,
      snapshot,
    });
    return snapshot;
  }

  getCursorSamples(graphId: string | null): readonly PresenceCursorSample[] {
    if (graphId === null) return EMPTY_CURSOR_SAMPLES;
    const cached = this.cursorCache.get(graphId);
    if (cached?.revision === this.revision) return cached.snapshot;

    const next: PresenceCursorSample[] = [];
    for (const participant of this.remoteParticipantsOnGraph(graphId)) {
      if (participant.cursor === null) continue;
      next.push({
        sessionId: participant.project_room_session_id,
        actorId: participant.actor.actor_id,
        displayName: participant.actor.display_name,
        color: actorColor(participant.actor.color),
        cursor: participant.cursor,
        sampleRevision:
          this.cursorRevisions.get(participant.project_room_session_id) ?? 0,
      });
    }
    const snapshot =
      cached && sameCursorSamples(cached.snapshot, next)
        ? cached.snapshot
        : next;
    this.cursorCache.set(graphId, {
      revision: this.revision,
      snapshot,
    });
    return snapshot;
  }

  getRemoteSelectionColors(
    graphId: string | null,
  ): ReadonlyMap<string, string> {
    if (graphId === null) return EMPTY_SELECTION_COLORS;
    const cached = this.selectionCache.get(graphId);
    if (cached?.revision === this.revision) return cached.snapshot;

    const next = new Map<string, string>();
    for (const participant of this.remoteParticipantsOnGraph(graphId)) {
      const color = actorColor(participant.actor.color);
      for (const nodeId of participant.selected_node_ids) {
        if (!next.has(nodeId)) next.set(nodeId, color);
      }
    }
    const snapshot =
      cached && sameMap(cached.snapshot, next) ? cached.snapshot : next;
    this.selectionCache.set(graphId, {
      revision: this.revision,
      snapshot,
    });
    return snapshot;
  }

  getRemoteDragTargets(
    graphId: string | null,
  ): ReadonlyMap<string, TransientNodePosition> {
    if (graphId === null) return EMPTY_DRAG_TARGETS;
    const cached = this.dragCache.get(graphId);
    if (cached?.revision === this.revision) return cached.snapshot;

    const next = new Map<string, TransientNodePosition>();
    for (const participant of this.remoteParticipantsOnGraph(graphId)) {
      for (const position of participant.transient_node_positions) {
        // Keep the existing rule: the later participant owns a contested node.
        next.set(position.node_id, position);
      }
    }
    const snapshot =
      cached && sameDragTargets(cached.snapshot, next) ? cached.snapshot : next;
    this.dragCache.set(graphId, {
      revision: this.revision,
      snapshot,
    });
    return snapshot;
  }

  private recordCursorArrival(participant: PresenceParticipant): void {
    if (participant.cursor === null) return;
    this.cursorSampleRevision += 1;
    this.cursorRevisions.set(
      participant.project_room_session_id,
      this.cursorSampleRevision,
    );
  }

  private publishChange(): void {
    const nextParticipants = [...this.participants.values()];
    if (!sameVisualParticipants(this.visualParticipants, nextParticipants)) {
      this.visualParticipants = nextParticipants;
    }
    this.revision += 1;
    for (const listener of this.listeners) listener();
  }

  private remoteParticipantsOnGraph(
    graphId: string,
  ): readonly PresenceParticipant[] {
    return this.visualParticipants.filter(
      (participant) =>
        participant.project_room_session_id !== this.localSessionId &&
        participant.graph_id === graphId,
    );
  }
}

export function sameVisualParticipants(
  left: readonly PresenceParticipant[],
  right: readonly PresenceParticipant[],
): boolean {
  if (left.length !== right.length) return false;
  return left.every((participant, index) => {
    const candidate = right[index];
    return (
      candidate !== undefined && sameVisualParticipant(participant, candidate)
    );
  });
}

function sameVisualParticipant(
  left: PresenceParticipant,
  right: PresenceParticipant,
): boolean {
  return (
    left.project_room_session_id === right.project_room_session_id &&
    left.actor.actor_id === right.actor.actor_id &&
    left.actor.display_name === right.actor.display_name &&
    left.actor.color === right.actor.color &&
    left.graph_id === right.graph_id &&
    samePoint(left.cursor, right.cursor) &&
    sameStrings(left.selected_node_ids, right.selected_node_ids) &&
    sameStrings(left.selected_edge_ids, right.selected_edge_ids) &&
    left.activity === right.activity &&
    sameStrings(left.activity_target_ids, right.activity_target_ids) &&
    sameTransientPositions(
      left.transient_node_positions,
      right.transient_node_positions,
    )
  );
}

function samePoint(left: PresencePoint | null, right: PresencePoint | null) {
  if (left === null || right === null) return left === right;
  return left.x === right.x && left.y === right.y;
}

function sameStrings(left: readonly string[], right: readonly string[]) {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function sameTransientPositions(
  left: readonly TransientNodePosition[],
  right: readonly TransientNodePosition[],
) {
  return (
    left.length === right.length &&
    left.every((position, index) => {
      const candidate = right[index];
      return (
        candidate !== undefined &&
        position.node_id === candidate.node_id &&
        position.x === candidate.x &&
        position.y === candidate.y
      );
    })
  );
}

function sameCollaborators(
  left: readonly PresenceCollaborator[],
  right: readonly PresenceCollaborator[],
): boolean {
  if (left.length !== right.length) return false;
  return left.every((collaborator, index) => {
    const candidate = right[index];
    return (
      candidate !== undefined &&
      collaborator.sessionId === candidate.sessionId &&
      collaborator.actorId === candidate.actorId &&
      collaborator.displayName === candidate.displayName &&
      collaborator.color === candidate.color &&
      collaborator.activity === candidate.activity &&
      sameStrings(collaborator.activityTargetIds, candidate.activityTargetIds)
    );
  });
}

function sameCursorSamples(
  left: readonly PresenceCursorSample[],
  right: readonly PresenceCursorSample[],
): boolean {
  if (left.length !== right.length) return false;
  return left.every((sample, index) => {
    const candidate = right[index];
    return (
      candidate !== undefined &&
      sample.sessionId === candidate.sessionId &&
      sample.actorId === candidate.actorId &&
      sample.displayName === candidate.displayName &&
      sample.color === candidate.color &&
      sample.cursor.x === candidate.cursor.x &&
      sample.cursor.y === candidate.cursor.y &&
      sample.sampleRevision === candidate.sampleRevision
    );
  });
}

function sameMap(
  left: ReadonlyMap<string, string>,
  right: ReadonlyMap<string, string>,
): boolean {
  if (left.size !== right.size) return false;
  for (const [key, value] of left) {
    if (right.get(key) !== value) return false;
  }
  return true;
}

function sameDragTargets(
  left: ReadonlyMap<string, TransientNodePosition>,
  right: ReadonlyMap<string, TransientNodePosition>,
): boolean {
  if (left.size !== right.size) return false;
  for (const [nodeId, position] of left) {
    const candidate = right.get(nodeId);
    if (
      candidate === undefined ||
      position.node_id !== candidate.node_id ||
      position.x !== candidate.x ||
      position.y !== candidate.y
    ) {
      return false;
    }
  }
  return true;
}
