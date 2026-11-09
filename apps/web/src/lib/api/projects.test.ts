import { afterEach, describe, expect, it, vi } from "vitest";

import type { CollaborativeHead } from "./contract";
import {
  applyNodeSecret,
  cancelRun,
  checkpointProject,
  createProject,
  deleteProject,
  getCollaborativeHead,
  getInstanceResult,
  getProjectNodeSecrets,
  graphFromProjectHead,
  listGraphInstances,
  listRuns,
  removeNodeSecret,
  startRun,
  submitProjectCommand,
} from "./projects";

/*
 * The Project HTTP surface: the document a Project holds, the commands that
 * change it, the checkpoints that retain it, the Runs that ask for freshness,
 * and the instances that hold results.
 *
 * What is asserted is the *contract*: the address, the verb, and the body. The
 * server's decisions belong to the API suites; that a `POST` to `/commands`
 * carries the whole batch, or that a result is addressed by its instance and
 * not by its Run, is a client-side promise this file can break.
 */

afterEach(() => vi.unstubAllGlobals());

const WORKSPACE_ID = "workspace/1";
const PROJECT_ID = "3f1a2b4c-5d6e-4f70-8192-a3b4c5d6e7f8";
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const NODE_ID = "22222222-2222-4222-8222-222222222222";

const json = (payload: unknown, status = 200) =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

/** The last call this client made, as [url, init]. */
function lastCall(): [string, RequestInit] {
  const fetchMock = vi.mocked(fetch);
  const call = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  expect(call).toBeDefined();
  return call;
}

function bodyOf(init: RequestInit): Record<string, unknown> {
  return JSON.parse(String(init.body)) as Record<string, unknown>;
}

const head = (overrides: Partial<CollaborativeHead> = {}): CollaborativeHead =>
  ({
    project_id: PROJECT_ID,
    workspace_id: WORKSPACE_ID,
    name: "Intake",
    room_epoch: "epoch-1",
    collaboration_sequence: 7,
    checkpoint_sequence: 5,
    checkpoint_revision: 3,
    updated_at: "2026-08-07T00:00:00Z",
    document: {
      graphs: [
        {
          id: GRAPH_ID,
          name: "Main",
          document: {
            schema_version: 7,
            nodes: [],
            edges: [],
            origins: [],
            presentation: {
              viewers: [],
              links: [],
              bindings: [],
              annotations: [],
            },
          },
        },
      ],
    },
    ...overrides,
  }) as unknown as CollaborativeHead;

describe("project HTTP API", () => {
  it("creates a Project with its first Graph, naming both", async () => {
    json({ id: PROJECT_ID });
    await createProject(WORKSPACE_ID, {
      project_id: PROJECT_ID,
      graph_id: GRAPH_ID,
      name: "Intake",
      graph_name: "Main",
    });
    const [url, init] = lastCall();
    expect(url).toBe("/api/v1/workspaces/workspace%2F1/projects");
    expect(init.method).toBe("POST");
    // The caller names both ids, so the address a person is taken to is known
    // before the write is confirmed.
    expect(bodyOf(init)).toEqual({
      project_id: PROJECT_ID,
      graph_id: GRAPH_ID,
      name: "Intake",
      graph_name: "Main",
    });
  });

  it("deletes only with the exact head it was shown, when it was shown one", async () => {
    json({});
    await deleteProject(WORKSPACE_ID, PROJECT_ID);
    expect(lastCall()[0]).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}`,
    );

    json({});
    await deleteProject(WORKSPACE_ID, PROJECT_ID, {
      expectedRoomEpoch: "epoch-1",
      expectedSequence: 7,
    });
    const [url, init] = lastCall();
    expect(init.method).toBe("DELETE");
    expect(url).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}` +
        `?expected_room_epoch=epoch-1&expected_sequence=7`,
    );
  });
});

describe("project head and commands", () => {
  it("reads the whole Project document from one address", async () => {
    json(head());
    const read = await getCollaborativeHead(WORKSPACE_ID, PROJECT_ID);
    const [url] = lastCall();
    expect(url).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/head`,
    );
    expect(read.document.graphs).toHaveLength(1);
  });

  it("projects one Graph out of the head, saving against the head's sequence", () => {
    const graph = graphFromProjectHead(head(), GRAPH_ID);
    expect(graph).toMatchObject({
      id: GRAPH_ID,
      name: "Main",
      revision: 7,
      updated_at: "2026-08-07T00:00:00Z",
    });
    // A Graph the Project does not hold is not there; the canvas shows a
    // missing Graph rather than editing the wrong one.
    expect(graphFromProjectHead(head(), "nope")).toBeNull();
  });

  it("submits a command batch as one unit and returns the receipt", async () => {
    json({
      receipt: {
        command_id: "req-1",
        room_epoch: "epoch-1",
        accepted_sequence: 8,
        outcome: "accepted",
        deduplicated: false,
      },
      head: head({ collaboration_sequence: 8 }),
    });
    const commands = [
      {
        kind: "in_graph" as const,
        graph_id: GRAPH_ID,
        command: { kind: "add_node" as const, node: { id: NODE_ID } },
      },
      {
        kind: "rename_project" as const,
        name: "Intake v2",
        expected_name: "Intake",
      },
    ];
    const result = await submitProjectCommand(WORKSPACE_ID, PROJECT_ID, {
      client_request_id: "req-1",
      commands,
    } as never);
    const [url, init] = lastCall();
    expect(url).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/commands`,
    );
    expect(init.method).toBe("POST");
    // The batch travels whole: a half-applied batch is not a unit of work.
    expect(bodyOf(init)["commands"]).toHaveLength(2);
    expect(result.receipt.accepted_sequence).toBe(8);
  });

  it("checkpoints the current project", async () => {
    json({ checkpoint: { revision: 4 } });
    await checkpointProject(WORKSPACE_ID, PROJECT_ID, {
      expected_name: "Intake",
    } as never);
    const [written, writeInit] = lastCall();
    expect(written).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/checkpoints`,
    );
    expect(writeInit.method).toBe("POST");
  });
});

describe("runs and instances", () => {
  it("asks for freshness by naming the targets of one Graph", async () => {
    json({ run_id: "run-1" });
    await startRun(WORKSPACE_ID, PROJECT_ID, {
      graph_id: GRAPH_ID,
      targets: [{ node_id: NODE_ID, call_path: [] }],
    });
    const [url, init] = lastCall();
    expect(url).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/runs`,
    );
    expect(init.method).toBe("POST");
    expect(bodyOf(init)).toEqual({
      graph_id: GRAPH_ID,
      targets: [{ node_id: NODE_ID, call_path: [] }],
    });
  });

  it("says which Runs it wants: the open ones, or the record", async () => {
    json({ runs: [] });
    await listRuns(WORKSPACE_ID, PROJECT_ID, { activeOnly: true });
    expect(lastCall()[0]).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/runs?active=true`,
    );

    json({ runs: [] });
    await listRuns(WORKSPACE_ID, PROJECT_ID, {});
    expect(lastCall()[0]).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/runs`,
    );
  });

  it("withdraws a Run at its own address", async () => {
    json({ run_id: "run-1" });
    await cancelRun(WORKSPACE_ID, PROJECT_ID, "run/1");
    const [url, init] = lastCall();
    expect(init.method).toBe("POST");
    expect(url).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/runs/run%2F1/cancel`,
    );
  });

  it("lists derived state for every instance of one Graph", async () => {
    json({ instances: [] });
    await listGraphInstances(WORKSPACE_ID, PROJECT_ID, "graph/1");
    expect(lastCall()[0]).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}` +
        `/graphs/graph%2F1/instances`,
    );
  });

  it("reads a result by the instance that owns it, call path and all", async () => {
    json({ state: "fresh" });
    await getInstanceResult(WORKSPACE_ID, PROJECT_ID, {
      graph_id: GRAPH_ID,
      node_id: NODE_ID,
      call_path: [GRAPH_ID, NODE_ID],
    });
    const [url] = lastCall();
    expect(
      url.startsWith(
        `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/instance-result?`,
      ),
    ).toBe(true);
    const query = new URL(url, "https://grafy.test").searchParams;
    expect(query.get("graph_id")).toBe(GRAPH_ID);
    expect(query.get("node_id")).toBe(NODE_ID);
    // The call path survives as the path it names, not as a flattened guess.
    expect(query.getAll("call_path")).toEqual([GRAPH_ID, NODE_ID]);
  });
});

describe("node secrets", () => {
  it("lists the secrets of one Graph's nodes", async () => {
    json({ secrets: [] });
    await getProjectNodeSecrets(WORKSPACE_ID, PROJECT_ID, "graph/1");
    const [url] = lastCall();
    expect(url).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}/node-secrets?graph_id=graph%2F1`,
    );
  });

  it("writes and removes a secret at the node it belongs to", async () => {
    // Both writes name the head they were made against: a secret is applied to
    // a document, and a stale one must not overwrite a newer revision.
    json({ name: "api_key" });
    await applyNodeSecret(
      WORKSPACE_ID,
      PROJECT_ID,
      "graph/1",
      "node/1",
      "api_key",
      {
        value: "secret",
        expected_head_sequence: 7,
      },
    );
    const [written, writeInit] = lastCall();
    expect(writeInit.method).toBe("PUT");
    expect(written).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}` +
        `/graphs/graph%2F1/nodes/node%2F1/secrets/api_key`,
    );

    json({});
    await removeNodeSecret(
      WORKSPACE_ID,
      PROJECT_ID,
      "graph/1",
      "node/1",
      "api_key",
      7,
    );
    const [removed, removeInit] = lastCall();
    expect(removeInit.method).toBe("DELETE");
    // A secret is removed from a document, so the caller says which revision it
    // was looking at; a stale removal is refused rather than silently applied.
    expect(removed).toBe(
      `/api/v1/workspaces/workspace%2F1/projects/${PROJECT_ID}` +
        `/graphs/graph%2F1/nodes/node%2F1/secrets/api_key` +
        `?expected_head_sequence=7`,
    );
  });
});
