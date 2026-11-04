import { describe, expect, it, vi } from "vitest";

import {
  ProjectRoomCommandError,
  ProjectRoomCommandOutbox,
  type ProjectRoomHeadPointer,
} from "./command-outbox";
import type {
  ProjectCommandAcceptedMessage,
  ProjectCommandReceiptMessage,
  ProjectCommandRejectedMessage,
  RoomProjectCommand,
} from "./protocol";

const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const EPOCH_ONE = "33333333-3333-4333-8333-333333333333";
const EPOCH_TWO = "44444444-4444-4444-8444-444444444444";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";

/** A Project-level command: it renames the Project, not one of its Graphs. */
function renameProject(name: string): RoomProjectCommand {
  return { kind: "rename_project", name, expected_name: "Room project" };
}

/** One command addressed inside a Graph, as a batch entry. */
function moveNode(nodeId: string, x: number): RoomProjectCommand {
  return {
    kind: "in_graph",
    graph_id: GRAPH_ID,
    command: { kind: "move_nodes", positions: [{ node_id: nodeId, x, y: 0 }] },
  };
}

/** A save batch: the Graph's new name and its new document travel together. */
function batch(name: string): readonly RoomProjectCommand[] {
  return [renameProject(name), moveNode("a", 10)];
}

function nextId(ids: string[]): () => string {
  let index = 0;
  return () => {
    const id = ids[index];
    index += 1;
    return id ?? `unplanned-command-${index}`;
  };
}

function acceptedMessage(
  commandId: string,
  sequence: number,
  overrides: Partial<ProjectCommandAcceptedMessage> = {},
): ProjectCommandAcceptedMessage {
  return {
    protocol_version: 1,
    type: "project.command.accepted",
    command_id: commandId,
    room_epoch: EPOCH_ONE,
    sequence,
    actor: {
      actor_id: "aaaa0000-0000-4000-8000-000000000001",
      display_name: "Owner",
      color: "emerald",
    },
    project_room_session_id: SESSION_ID,
    commands: batch("Renamed"),
    ...overrides,
  };
}

function receiptMessage(
  commandId: string,
  overrides: Partial<ProjectCommandReceiptMessage> = {},
): ProjectCommandReceiptMessage {
  return {
    protocol_version: 1,
    type: "project.command.receipt",
    command_id: commandId,
    outcome: "accepted",
    accepted_room_epoch: EPOCH_ONE,
    accepted_sequence: 5,
    current_room_epoch: EPOCH_ONE,
    current_sequence: 5,
    deduplicated: false,
    requires_head_rehydration: false,
    ...overrides,
  };
}

function rejectedMessage(
  commandId: string,
  overrides: Partial<ProjectCommandRejectedMessage> = {},
): ProjectCommandRejectedMessage {
  return {
    protocol_version: 1,
    type: "project.command.rejected",
    command_id: commandId,
    error_code: "head_conflict",
    detail: "Collaborative head moved: expected sequence 4, actual 5.",
    current_room_epoch: EPOCH_ONE,
    current_sequence: 5,
    ...overrides,
  };
}

describe("ProjectRoomCommandOutbox", () => {
  it("sends a whole batch as one frame and replays an interrupted batch first across an epoch change", async () => {
    let head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 4,
    };
    const onHeadRefreshRequired = vi.fn();
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a", "command-b", "command-c"]),
      onHeadRefreshRequired,
    });

    const first = outbox.submit(batch("Committed during disconnect"));
    const second = outbox.submit([renameProject("Queued second")]);
    const third = outbox.submit([renameProject("Queued third")]);

    expect(first.sends.map((send) => send.message.command_id)).toEqual([
      "command-a",
    ]);
    // One batch is one unit of work: one frame carrying every command in order.
    expect(first.sends[0]?.message).toMatchObject({
      type: "project.command.submit",
      room_epoch: EPOCH_ONE,
      observed_sequence: 4,
    });
    expect(first.sends[0]?.message.commands).toEqual([
      renameProject("Committed during disconnect"),
      moveNode("a", 10),
    ]);
    expect(second.sends).toEqual([]);
    expect(third.sends).toEqual([]);

    // The socket dropped with command-a in flight: it goes back to the front so
    // its idempotency identity (epoch + observed sequence) can be replayed.
    outbox.interruptInFlight();

    // The server reset the room epoch and the driver replaced the head.
    head = { room_epoch: EPOCH_TWO, collaboration_sequence: 0 };
    const resumed = outbox.finishHeadRehydration();
    expect(resumed).toHaveLength(1);
    expect(resumed[0]?.message).toMatchObject({
      command_id: "command-a",
      room_epoch: EPOCH_ONE,
      observed_sequence: 4,
    });
    expect(resumed[0]?.message.commands).toEqual([
      renameProject("Committed during disconnect"),
      moveNode("a", 10),
    ]);

    // command-a is replayed in the old epoch while the room already lives in
    // the new one, so its receipt still settles it and hands the slot to b.
    const afterReplay = outbox.applyReceipt(
      receiptMessage("command-a", {
        outcome: "idempotent_replay",
        accepted_sequence: 5,
        current_room_epoch: EPOCH_TWO,
        current_sequence: 0,
        deduplicated: true,
      }),
    );
    expect(afterReplay[0]?.message).toMatchObject({
      command_id: "command-b",
      room_epoch: EPOCH_TWO,
      observed_sequence: 0,
    });
    await expect(first.promise).resolves.toMatchObject({
      receipt: { accepted_sequence: 5, deduplicated: true },
      accepted: null,
    });

    head = { room_epoch: EPOCH_TWO, collaboration_sequence: 1 };
    const afterSecond = outbox.applyReceipt(
      receiptMessage("command-b", {
        accepted_sequence: 1,
        current_room_epoch: EPOCH_TWO,
        current_sequence: 1,
      }),
    );
    expect(afterSecond[0]?.message).toMatchObject({
      command_id: "command-c",
      room_epoch: EPOCH_TWO,
      observed_sequence: 1,
    });

    head = { room_epoch: EPOCH_TWO, collaboration_sequence: 2 };
    expect(
      outbox.applyReceipt(
        receiptMessage("command-c", {
          accepted_sequence: 2,
          current_room_epoch: EPOCH_TWO,
          current_sequence: 2,
        }),
      ),
    ).toEqual([]);
    await expect(second.promise).resolves.toMatchObject({
      receipt: { accepted_sequence: 1 },
    });
    await expect(third.promise).resolves.toMatchObject({
      receipt: { accepted_sequence: 2 },
    });
    expect(onHeadRefreshRequired).not.toHaveBeenCalled();
  });

  it("holds a receipt that arrives before its accepted and settles it with that accepted", async () => {
    let head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 4,
    };
    const onHeadRefreshRequired = vi.fn();
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a"]),
      onHeadRefreshRequired,
    });

    const submitted = outbox.submit(batch("Receipt first"));
    expect(submitted.sends).toHaveLength(1);

    const held = outbox.applyReceipt(
      receiptMessage("command-a", {
        accepted_sequence: 5,
        current_room_epoch: EPOCH_ONE,
        current_sequence: 5,
      }),
    );
    expect(held).toEqual([]);
    expect(onHeadRefreshRequired).toHaveBeenCalledOnce();

    let settled = false;
    void submitted.promise.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    // The accepted finally lands. The receipt already consumed the local
    // marker, so this accepted is reported to listeners as a non-local fanout
    // while still being the payload the caller's promise resolves with.
    expect(outbox.recordAccepted(acceptedMessage("command-a", 5))).toBe(false);
    head = { room_epoch: EPOCH_ONE, collaboration_sequence: 5 };

    expect(outbox.afterHeadApplied()).toEqual([]);
    await expect(submitted.promise).resolves.toMatchObject({
      receipt: { accepted_sequence: 5 },
      accepted: { sequence: 5 },
    });
  });

  it("resolves a receipt that the head already covers with no accepted at all", async () => {
    const head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 5,
    };
    const onHeadRefreshRequired = vi.fn();
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a"]),
      onHeadRefreshRequired,
    });

    const submitted = outbox.submit(batch("Replayed commit"));
    const sends = outbox.applyReceipt(
      receiptMessage("command-a", {
        outcome: "idempotent_replay",
        accepted_sequence: 5,
        current_room_epoch: EPOCH_ONE,
        current_sequence: 5,
        deduplicated: true,
      }),
    );

    expect(sends).toEqual([]);
    expect(onHeadRefreshRequired).not.toHaveBeenCalled();
    await expect(submitted.promise).resolves.toEqual({
      receipt: expect.objectContaining({ deduplicated: true }),
      accepted: null,
    });
  });

  it("counts only the first accepted as local and keeps the latest accepted batch", async () => {
    let head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 4,
    };
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a"]),
    });

    const submitted = outbox.submit(batch("Fanout twice"));
    expect(outbox.recordAccepted(acceptedMessage("command-a", 5))).toBe(true);
    expect(
      outbox.recordAccepted(
        acceptedMessage("command-a", 5, {
          commands: batch("Redelivered rename"),
        }),
      ),
    ).toBe(false);

    head = { room_epoch: EPOCH_ONE, collaboration_sequence: 5 };
    outbox.applyReceipt(receiptMessage("command-a"));

    const result = await submitted.promise;
    expect(result.accepted).toMatchObject({
      sequence: 5,
      commands: batch("Redelivered rename"),
    });
  });

  it("ignores late messages for a command whose promise already rejected", async () => {
    let head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 4,
    };
    const onCommandRejected = vi.fn();
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a", "command-b"]),
      onCommandRejected,
    });

    const rejected = outbox.submit([renameProject("Conflicting")]);
    outbox.applyRejected(rejectedMessage("command-a"));
    expect(onCommandRejected).toHaveBeenCalledOnce();
    await expect(rejected.promise).rejects.toMatchObject({
      name: "ProjectRoomCommandError",
      errorCode: "head_conflict",
    });

    // Late accepted and receipt for the same id must not resolve or re-send.
    expect(outbox.recordAccepted(acceptedMessage("command-a", 5))).toBe(false);
    expect(outbox.applyReceipt(receiptMessage("command-a"))).toEqual([]);
    expect(outbox.pendingReceiptIsCovered()).toBe(false);

    // The rejected command also parked the drain; a queued command resumes it.
    const queued = outbox.submit([renameProject("After conflict")]);
    expect(queued.sends).toEqual([]);
    head = { room_epoch: EPOCH_ONE, collaboration_sequence: 5 };
    const resumed = outbox.finishHeadRehydration();
    expect(resumed.map((send) => send.message.command_id)).toEqual([
      "command-b",
    ]);
    queued.promise.catch(() => undefined);
  });

  it("rejects the caller when the driver cannot write a returned frame", async () => {
    const head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 4,
    };
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a", "command-b"]),
    });

    const first = outbox.submit(batch("Never written"));
    expect(first.sends).toHaveLength(1);
    outbox.sendFailed(
      first.sends[0]?.commandId ?? "",
      new Error("socket send rejected"),
    );
    await expect(first.promise).rejects.toThrow("socket send rejected");

    // A non-Error failure still carries the command id and an error code.
    const second = outbox.submit(batch("Second"));
    expect(second.sends).toHaveLength(1);
    outbox.sendFailed(second.sends[0]?.commandId ?? "", "socket exploded");
    await expect(second.promise).rejects.toBeInstanceOf(
      ProjectRoomCommandError,
    );
    await expect(second.promise).rejects.toMatchObject({
      commandId: "command-b",
      errorCode: "send_failed",
    });
  });

  it("supersedes an unsent snapshot batch by its inner kind, addressed or bare", async () => {
    let head: ProjectRoomHeadPointer | null = {
      room_epoch: EPOCH_ONE,
      collaboration_sequence: 4,
    };
    const outbox = new ProjectRoomCommandOutbox({
      headPointer: () => head,
      createCommandId: nextId(["command-a", "command-b", "command-c"]),
    });

    const replaceDocument = (
      viewerId: string,
    ): readonly RoomProjectCommand[] => [
      {
        kind: "in_graph",
        graph_id: GRAPH_ID,
        command: {
          kind: "replace_document",
          document: {
            schema_version: 7,
            nodes: [],
            edges: [],
            origins: [],
            agents: [],
            presentation: {
              viewers: [{ id: viewerId, position: { x: 1, y: 1 } }],
              links: [],
              bindings: [],
              annotations: [],
            },
          },
        },
      },
    ];

    const first = outbox.submit([renameProject("In flight")]);
    expect(first.sends).toHaveLength(1);

    // A save snapshot replaces a whole body, so an unsent one is worthless as
    // soon as a newer snapshot of the same kind is queued.
    const stale = outbox.submit(replaceDocument("stale"));
    const latest = outbox.submit(replaceDocument("latest"));
    await expect(stale.promise).rejects.toMatchObject({
      errorCode: "superseded",
    });
    expect(latest.sends).toEqual([]);

    head = { room_epoch: EPOCH_ONE, collaboration_sequence: 5 };
    const drained = outbox.finishHeadRehydration();
    expect(drained).toEqual([]);

    // The in-flight Project rename settles, then the surviving snapshot goes.
    const released = outbox.applyReceipt(receiptMessage("command-a"));
    expect(released[0]?.message.commands).toEqual(replaceDocument("latest"));
    await expect(first.promise).resolves.toMatchObject({
      receipt: { accepted_sequence: 5 },
    });
    latest.promise.catch(() => undefined);
  });
});
