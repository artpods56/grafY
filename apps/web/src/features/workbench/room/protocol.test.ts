import { describe, expect, it } from "vitest";

import { parseServerRoomMessage } from "./protocol";

const ACTOR = {
  actor_id: "00000000-0000-4000-8000-000000000001",
  display_name: "Owner",
  color: "emerald",
};
const ROOM_EPOCH = "33333333-3333-4333-8333-333333333333";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";

const renameOne = {
  kind: "rename_graph",
  name: "One",
  expected_name: "Room graph",
};
const renameTwo = {
  kind: "rename_graph",
  name: "Two",
  expected_name: "One",
};

/** The diff of a batch that changed no entity. */
const EMPTY_DIFF = {
  name: null,
  nodes: {},
  edges: {},
  origins: {},
  viewers: {},
  links: {},
  bindings: {},
  annotations: {},
};

function acceptedFixture(overrides: Record<string, unknown> = {}) {
  return {
    protocol_version: 1,
    type: "graph.command.accepted",
    command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    room_epoch: ROOM_EPOCH,
    sequence: 5,
    actor: ACTOR,
    graph_room_session_id: SESSION_ID,
    command: null,
    commands: [renameOne],
    diff: EMPTY_DIFF,
    ...overrides,
  };
}

describe("parseServerRoomMessage graph.command.accepted", () => {
  it("parses an accepted single-command batch with its command", () => {
    const message = parseServerRoomMessage(
      acceptedFixture({ command: renameOne }),
    );
    expect(message).toMatchObject({
      type: "graph.command.accepted",
      sequence: 5,
      command: renameOne,
      commands: [renameOne],
    });
  });

  it("parses an accepted multi-command batch with a null command", () => {
    const message = parseServerRoomMessage(
      acceptedFixture({ command: null, commands: [renameOne, renameTwo] }),
    );
    expect(message).toMatchObject({
      type: "graph.command.accepted",
      command: null,
      commands: [renameOne, renameTwo],
    });
  });

  it("rejects an accepted message without commands", () => {
    const fixture = acceptedFixture();
    delete (fixture as { commands?: unknown }).commands;
    expect(parseServerRoomMessage(fixture)).toBeNull();
  });

  it("rejects an accepted message with an empty command batch", () => {
    expect(
      parseServerRoomMessage(acceptedFixture({ commands: [] })),
    ).toBeNull();
  });

  it("rejects an accepted message whose batch contains a non-record", () => {
    expect(
      parseServerRoomMessage(
        acceptedFixture({ commands: [renameOne, "nope"] }),
      ),
    ).toBeNull();
  });

  it("parses the entity diff carried by an accepted message", () => {
    const message = parseServerRoomMessage(
      acceptedFixture({
        diff: {
          ...EMPTY_DIFF,
          name: { before: "One", after: "Two" },
          nodes: {
            n1: {
              before: null,
              after: { id: "n1", kind: "builtin", position: { x: 1, y: 2 } },
            },
          },
        },
      }),
    );
    expect(message).toMatchObject({
      type: "graph.command.accepted",
      diff: {
        name: { before: "One", after: "Two" },
        nodes: { n1: { before: null } },
      },
    });
  });

  it("keeps an entity whose id is __proto__ as an own diff entry", () => {
    // JSON.parse makes "__proto__" an own key; the parser must not turn it
    // into a prototype assignment that drops the entity.
    const raw: unknown = JSON.parse(
      JSON.stringify(acceptedFixture()).replace(
        '"nodes":{}',
        '"nodes":{"__proto__":{"before":null,"after":{"id":"__proto__"}}}',
      ),
    );
    const message = parseServerRoomMessage(raw);
    expect(message?.type).toBe("graph.command.accepted");
    if (message?.type !== "graph.command.accepted") return;
    expect(Object.hasOwn(message.diff.nodes, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(message.diff.nodes)).toBe(Object.prototype);
  });

  it("rejects an accepted message without a diff", () => {
    const fixture = acceptedFixture();
    delete (fixture as { diff?: unknown }).diff;
    expect(parseServerRoomMessage(fixture)).toBeNull();
  });

  it("rejects a diff whose entity id does not match its key", () => {
    expect(
      parseServerRoomMessage(
        acceptedFixture({
          diff: {
            ...EMPTY_DIFF,
            nodes: { n1: { before: null, after: { id: "other" } } },
          },
        }),
      ),
    ).toBeNull();
    expect(
      parseServerRoomMessage(
        acceptedFixture({
          diff: {
            ...EMPTY_DIFF,
            edges: { e1: { before: { id: "e1" }, after: { id: "nope" } } },
          },
        }),
      ),
    ).toBeNull();
  });

  it("rejects a diff whose name change is not a before/after pair", () => {
    for (const name of [
      { before: "One" },
      { before: "One", after: 2 },
      { before: 1, after: "Two" },
      "Two",
      [],
    ]) {
      expect(
        parseServerRoomMessage(
          acceptedFixture({ diff: { ...EMPTY_DIFF, name } }),
        ),
      ).toBeNull();
    }
  });

  it("rejects a diff whose collection is missing or holds a malformed change", () => {
    const missingCollection = { ...EMPTY_DIFF };
    delete (missingCollection as { bindings?: unknown }).bindings;
    expect(
      parseServerRoomMessage(acceptedFixture({ diff: missingCollection })),
    ).toBeNull();
    expect(
      parseServerRoomMessage(
        acceptedFixture({
          diff: { ...EMPTY_DIFF, links: { l1: { before: null } } },
        }),
      ),
    ).toBeNull();
    expect(
      parseServerRoomMessage(
        acceptedFixture({ diff: { ...EMPTY_DIFF, nodes: [] } }),
      ),
    ).toBeNull();
  });

  it("parses a null name change and an absent one the same way", () => {
    expect(
      parseServerRoomMessage(
        acceptedFixture({ diff: { ...EMPTY_DIFF, name: null } }),
      ),
    ).toMatchObject({ diff: { name: null } });
  });
});

function rejectedFixture(overrides: Record<string, unknown> = {}) {
  return {
    protocol_version: 1,
    type: "graph.command.rejected",
    command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    error_code: "field_conflict",
    detail: "Name on graph changed",
    command_index: 1,
    current_room_epoch: ROOM_EPOCH,
    current_sequence: 5,
    ...overrides,
  };
}

describe("parseServerRoomMessage graph.command.rejected command_index", () => {
  it("parses a rejection that names the failing command", () => {
    expect(parseServerRoomMessage(rejectedFixture())).toMatchObject({
      type: "graph.command.rejected",
      error_code: "field_conflict",
      command_index: 1,
    });
  });

  it("parses a rejection whose command index is null", () => {
    expect(
      parseServerRoomMessage(rejectedFixture({ command_index: null })),
    ).toMatchObject({ command_index: null });
  });

  it("parses a rejection from a server that does not send a command index", () => {
    const fixture = rejectedFixture();
    delete (fixture as { command_index?: unknown }).command_index;
    expect(parseServerRoomMessage(fixture)).toMatchObject({
      command_index: null,
    });
  });

  it("rejects a command index that is not a non-negative integer", () => {
    for (const commandIndex of [-1, 1.5, "1", true]) {
      expect(
        parseServerRoomMessage(
          rejectedFixture({ command_index: commandIndex }),
        ),
      ).toBeNull();
    }
  });
});
