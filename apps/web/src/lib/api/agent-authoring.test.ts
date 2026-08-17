import { afterEach, describe, expect, it, vi } from "vitest";

import {
  agentDraftProgressFromCreate,
  agentDraftProgressFromDetail,
  agentDraftProgressFromFollowUp,
  agentDraftProgressFromNodeSpec,
  approveAgentBuild,
  cancelAgentRun,
  createAgentDraft,
  createAgentEnvironment,
  getAgentBuildReview,
  getAgentBuildReviewFile,
  getAgentDraft,
  getAgentRun,
  listAgentEnvironments,
  publishAgentBuild,
  queueAgentFollowUp,
  upsertAgentNodeSpec,
  watchAgentRun,
} from "./agent-authoring";
import type { NodeRegistry, NodeSpec } from "./contract";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("agent authoring API", () => {
  it("lists workspace environments through the encoded tenant route", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify({ environments: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetch);

    await expect(listAgentEnvironments("workspace / one")).resolves.toEqual({
      environments: [],
    });
    expect(fetch.mock.calls[0]?.[0]).toContain(
      "/v1/workspaces/workspace%20%2F%20one/agent-authoring/environments",
    );
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ method: "GET" });
  });

  it("creates a named uv environment with an abortable request", async () => {
    const environment = {
      id: "environment-1",
      name: "Python lab",
      profile_slug: "python-uv",
      provider: "daytona",
      status: "ready",
      active_run_id: null,
      failure_message: null,
      created_at: "2026-08-16T10:00:00Z",
      updated_at: "2026-08-16T10:00:00Z",
      last_used_at: null,
    };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(environment), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();

    await expect(
      createAgentEnvironment(
        "workspace-1",
        { name: "Python lab", profile_slug: "python-uv" },
        controller.signal,
      ),
    ).resolves.toEqual(environment);
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({ name: "Python lab", profile_slug: "python-uv" }),
    });
  });

  it("creates a connected draft through the graph-scoped atomic endpoint", async () => {
    const payload = { marker: "created" };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(JSON.stringify(payload), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetch);
    const input = {
      prompt: "Append a value to each text item",
      idempotency_key: "8d351551-d12f-42c6-b257-509b3d15bb67",
      environment_id: "0ea8f949-d698-4a4d-ac50-df05b72bd53e",
      anchor: {
        node_id: "source-node",
        port_name: "texts",
        direction: "downstream" as const,
        artifact_type: { id: "scalar.text", schema_version: 1 },
        shape: "many" as const,
        collection_mode: "direct" as const,
      },
      placement: {
        node_id: "node-generated",
        edge_id: "edge-generated",
        x: 420,
        y: 180,
        command_id: "8d351551-d12f-42c6-b257-509b3d15bb67",
        room_epoch: "b1a33fc4-ac5c-415a-8669-f83eb81eb467",
        observed_sequence: 7,
      },
    };
    const controller = new AbortController();

    await expect(
      createAgentDraft("workspace / one", "graph / one", input, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetch.mock.calls[0]?.[0]).toContain(
      "/v1/workspaces/workspace%20%2F%20one/agent-authoring/graphs/graph%20%2F%20one/drafts",
    );
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify(input),
    });
  });

  it("uses the build-scoped approval id returned by approval when publishing", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const url = String(input);
      if (url.endsWith("/approval")) {
        return new Response(
          JSON.stringify({ id: "approval-exact", capability_digest: "a".repeat(64) }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ release: {}, node_spec: {} }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetch);

    const approval = await approveAgentBuild(
      "workspace / one",
      "build / one",
      "a".repeat(64),
    );
    await publishAgentBuild(
      "workspace / one",
      "build / one",
      approval.id,
    );

    expect(fetch.mock.calls[0]?.[0]).toContain(
      "/agent-authoring/builds/build%20%2F%20one/approval",
    );
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      body: JSON.stringify({ capability_digest: "a".repeat(64) }),
    });
    expect(fetch.mock.calls[1]?.[0]).toContain(
      "/agent-authoring/builds/build%20%2F%20one/publish",
    );
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({
      body: JSON.stringify({ capability_approval_id: "approval-exact" }),
    });
  });

  it("queues follow-up work on the same thread and publishes with exact graph promotion", async () => {
    const fetch = vi.fn(async (
      input: RequestInfo | URL,
      _init?: RequestInit,
    ) => {
      void _init;
      return new Response(JSON.stringify({ url: String(input) }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetch);
    const followUp = {
      prompt: "Preserve empty values",
      idempotency_key: "b35b5932-0e8c-4baa-b813-0a3e43e15d0f",
      draft_node_ids: ["draft-1"],
    };
    const promotion = {
      graph_id: "graph-1",
      node_id: "node-1",
      command_id: "08cdef48-dbf5-42f6-a2c5-7c468f77fd5e",
      room_epoch: "208b5d15-fdd4-4e83-b54f-fb2a4367276d",
      observed_sequence: 14,
    };

    await queueAgentFollowUp("workspace", "thread / one", followUp);
    await publishAgentBuild("workspace", "build-2", "approval-2", promotion);

    expect(fetch.mock.calls[0]?.[0]).toContain(
      "/threads/thread%20%2F%20one/runs",
    );
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      body: JSON.stringify(followUp),
    });
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({
      body: JSON.stringify({
        capability_approval_id: "approval-2",
        graph_promotion: promotion,
      }),
    });
  });

  it("reads drafts and runs and cancels through their encoded control routes", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify({ url: String(input), method: init?.method }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await getAgentDraft("workspace", "draft / one");
    await getAgentRun("workspace", "run / one");
    await cancelAgentRun("workspace", "run / one");

    expect(fetch.mock.calls.map(([input, init]) => [String(input), init?.method]))
      .toEqual([
        [expect.stringContaining("/drafts/draft%20%2F%20one"), "GET"],
        [expect.stringContaining("/runs/run%20%2F%20one"), "GET"],
        [expect.stringContaining("/runs/run%20%2F%20one"), "DELETE"],
      ]);
  });

  it("loads curated build review metadata and one encoded source path", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) =>
      new Response(JSON.stringify({ url: String(input) }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await getAgentBuildReview("workspace", "build / one");
    await getAgentBuildReviewFile(
      "workspace",
      "build / one",
      "src/my node.py",
    );

    expect(fetch.mock.calls.map(([input]) => String(input))).toEqual([
      expect.stringContaining("/builds/build%20%2F%20one/review"),
      expect.stringContaining(
        "/builds/build%20%2F%20one/review/files/src/my%20node.py",
      ),
    ]);
  });
});

function authoringResponse() {
  const capabilityDigest = "b".repeat(64);
  return {
    environment: { id: "environment-1" },
    thread: { id: "thread-1" },
    draft: { id: "draft-1", status: "authoring", published_revision: 0 },
    run: { id: "run-1", status: "running", error: null },
    build: {
      id: "build-1",
      status: "coding",
      capabilities: null,
      failure_message: null,
    },
    node_spec: {},
    anchor_port: {},
    head: {},
    receipt: {},
    capabilityDigest,
  } as never;
}

describe("agent run lifecycle", () => {
  it("tracks a follow-up as the next operator version without replacing the release", () => {
    const previous = {
      ...agentDraftProgressFromCreate(authoringResponse()),
      state: "published" as const,
      releaseRevision: 1,
      targetOperatorVersion: 1,
    };
    const progress = agentDraftProgressFromFollowUp({
      environment: { id: "environment-1" },
      thread: { id: "thread-1", event_sequence: 20 },
      run: { id: "run-2", status: "running", error: null },
      builds: [{
        id: "build-2",
        draft_node_id: "draft-1",
        status: "coding",
        capabilities: null,
        failure_message: null,
      }],
      node_specs: [{
        operator_version: 2,
        agent_authoring: { draft_node_id: "draft-1" },
      }],
    } as never, "draft-1", previous);

    expect(progress).toMatchObject({
      runId: "run-2",
      buildId: "build-2",
      state: "coding",
      releaseRevision: 1,
      targetOperatorVersion: 2,
      lastEventSequence: 20,
    });
    const releasedV1 = {
      operator_id: "generated.node.draft-1",
      operator_version: 1,
      agent_authoring: {
        draft_node_id: "draft-1",
        status: "published" as const,
        runnable: true,
        release_revision: 1,
      },
    } as NodeSpec;
    expect(agentDraftProgressFromNodeSpec(releasedV1, progress)?.state).toBe(
      "coding",
    );
  });

  it("hydrates the latest durable run, build, approval, and replay cursor", () => {
    const progress = agentDraftProgressFromDetail({
      environment: { id: "environment-1" },
      thread: { id: "thread-1", event_sequence: 12 },
      draft: {
        id: "draft-1",
        status: "published",
        published_revision: 2,
      },
      latest_run: { id: "run-1", status: "completed", error: null },
      latest_build: {
        id: "build-1",
        status: "published",
        capabilities: { digest: "a".repeat(64) },
        failure_message: null,
      },
      capability_approval: null,
      release: {
        revision: 2,
        capability_approval_id: "approval-1",
      },
      node_spec: {},
    } as never);

    expect(progress).toMatchObject({
      draftId: "draft-1",
      runId: "run-1",
      buildId: "build-1",
      capabilityApprovalId: "approval-1",
      releaseRevision: 2,
      lastEventSequence: 12,
    });
  });

  it("hydrates an approved build before it has a published release", () => {
    const progress = agentDraftProgressFromDetail({
      environment: { id: "environment-1" },
      thread: { id: "thread-1", event_sequence: 13 },
      draft: {
        id: "draft-1",
        status: "awaiting_approval",
        published_revision: 0,
      },
      latest_run: { id: "run-1", status: "completed", error: null },
      latest_build: {
        id: "build-1",
        status: "awaiting_approval",
        capabilities: { digest: "a".repeat(64) },
        failure_message: null,
      },
      capability_approval: {
        id: "approval-before-publish",
      },
      release: null,
      node_spec: {},
    } as never);

    expect(progress).toMatchObject({
      capabilityApprovalId: "approval-before-publish",
      releaseRevision: null,
    });
  });

  it("derives durable draft state from registry metadata after a reload", () => {
    const draftSpec = {
      operator_id: "generated.node.draft-1",
      operator_version: 1,
      agent_authoring: {
        draft_node_id: "draft-1",
        status: "authoring",
        runnable: false,
        release_revision: null,
      },
    } as NodeSpec;
    const draft = agentDraftProgressFromNodeSpec(draftSpec);
    expect(draft).toMatchObject({
      draftId: "draft-1",
      state: "authoring",
      runId: null,
    });

    const publishedSpec = {
      ...draftSpec,
      agent_authoring: {
        ...draftSpec.agent_authoring!,
        status: "published" as const,
        runnable: true,
        release_revision: 1,
      },
    };
    expect(agentDraftProgressFromNodeSpec(publishedSpec, {
      ...draft!,
      state: "testing",
    })).toMatchObject({ state: "published", releaseRevision: 1 });
  });

  it("surfaces catalog awaiting-approval over a stale queued canvas draft", () => {
    const spec = {
      operator_id: "generated.node.draft-1",
      operator_version: 1,
      agent_authoring: {
        draft_node_id: "draft-1",
        status: "awaiting_approval" as const,
        runnable: false,
        release_revision: null,
      },
    } as NodeSpec;
    const queued = {
      ...agentDraftProgressFromCreate(authoringResponse()),
      state: "queued" as const,
      targetOperatorVersion: 1,
    };

    expect(agentDraftProgressFromNodeSpec(spec, queued)).toMatchObject({
      draftId: "draft-1",
      buildId: "build-1",
      state: "awaiting_approval",
    });
  });

  it("replaces the provisional contract with the published registry spec", () => {
    const provisional = {
      operator_id: "generated.node.draft-1",
      operator_version: 1,
      title: "Draft",
    } as NodeSpec;
    const published = {
      ...provisional,
      title: "Published",
      agent_authoring: {
        draft_node_id: "draft-1",
        status: "published" as const,
        runnable: true,
        release_revision: 1,
      },
    };
    const registry = {
      plugins: [],
      artifact_types: [],
      artifact_conversions: [],
      unavailable_modules: [],
      nodes: [provisional],
    } as NodeRegistry;

    expect(upsertAgentNodeSpec(registry, published).nodes).toEqual([published]);
  });

  it("resumes SSE after the durable cursor and reconnects from the last event", async () => {
    const encoder = new TextEncoder();
    const events = [
      {
        id: "event-7",
        thread_id: "thread-1",
        run_id: "run-1",
        sequence: 7,
        kind: "build_status_changed",
        message: "Tests started",
        draft_node_id: "draft-1",
        build_attempt_id: "build-1",
        run_status: "running",
        build_status: "testing",
        capability_digest: null,
        release_revision: null,
        created_at: "2026-08-17T10:00:00Z",
      },
      {
        id: "event-8",
        thread_id: "thread-1",
        run_id: "run-1",
        sequence: 8,
        kind: "run_status_changed",
        message: "Run completed",
        draft_node_id: "draft-1",
        build_attempt_id: "build-1",
        run_status: "completed",
        build_status: "awaiting_approval",
        capability_digest: "d".repeat(64),
        release_revision: null,
        created_at: "2026-08-17T10:00:01Z",
      },
    ];
    const fetch = vi.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => {
      void _input;
      void _init;
      const event = events[fetch.mock.calls.length - 1]!;
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                `id: ${event.sequence}\nevent: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`,
              ),
            );
            controller.close();
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      );
    });
    vi.stubGlobal("fetch", fetch);
    const initial = {
      ...agentDraftProgressFromCreate(authoringResponse()),
      lastEventSequence: 6,
    };
    const onProgress = vi.fn();
    const stop = watchAgentRun({
      workspaceId: "workspace / one",
      initial,
      onProgress,
      pollingIntervalMs: 1,
    });

    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(fetch.mock.calls[0]?.[0]).toContain(
      "/api/v1/workspaces/workspace%20%2F%20one/agent-authoring/runs/run-1/events?after_sequence=6",
    );
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      credentials: "same-origin",
      headers: expect.objectContaining({ "Last-Event-ID": "6" }),
    });
    expect(fetch.mock.calls[1]?.[0]).toContain("after_sequence=7");
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({
      headers: expect.objectContaining({ "Last-Event-ID": "7" }),
    });
    expect(onProgress).toHaveBeenLastCalledWith(expect.objectContaining({
      draftId: "draft-1",
      state: "awaiting_approval",
      lastEventSequence: 8,
    }));
    stop();
  });

  it("falls back to run-detail polling after repeated stream failures", async () => {
    const initial = agentDraftProgressFromCreate(authoringResponse());
    const manifest = {
      outbound_http_origins: ["https://api.example.test"],
      secret_refs: [],
      object_store: [],
      runtime: {
        cpu_millis: 500,
        memory_megabytes: 128,
        wall_time_seconds: 30,
        process_count: 1,
        input_bytes: 1024,
        output_bytes: 2048,
      },
      digest: "c".repeat(64),
    };
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/events?")) {
        return new Response(null, { status: 503, statusText: "Unavailable" });
      }
      return new Response(
        JSON.stringify({
          run: {
            id: "run-1",
            environment_id: "environment-1",
            status: "awaiting_approval",
            error: null,
          },
          builds: [
            {
              id: "build-1",
              draft_node_id: "draft-1",
              status: "awaiting_approval",
              capabilities: manifest,
              failure_message: null,
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetch);
    const onProgress = vi.fn();
    const stop = watchAgentRun({
      workspaceId: "workspace",
      initial,
      onProgress,
      pollingIntervalMs: 1,
    });

    await vi.waitFor(() => expect(onProgress).toHaveBeenCalled());
    expect(onProgress).toHaveBeenLastCalledWith(
      expect.objectContaining({
        state: "awaiting_approval",
        capabilityDigest: manifest.digest,
        capabilities: manifest,
      }),
    );
    const callsAfterSettled = fetch.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetch).toHaveBeenCalledTimes(callsAfterSettled);
    stop();
  });
});
