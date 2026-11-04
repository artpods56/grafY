import { expect, test as base } from "@playwright/test";
import type { Page, WebSocketRoute } from "@playwright/test";

import { applyRoomCommandsToHead } from "../src/features/workbench/room/room-command-bridge";
import type { RoomProjectCommand } from "../src/features/workbench/room/protocol";
import type {
  ActiveRunSummary,
  ArtifactOutputValue,
  CollaborativeHead,
  InstanceResult,
  InstanceState,
  NodeRegistry,
  ProjectList,
  ProjectSummary,
  Run,
  Session,
  Workspace,
  WorkspaceInvitationForRecipient,
} from "../src/lib/api/contract";
import { libraryStub } from "./library-folders-stub";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const WORKBENCH_PATH = "/workspaces/mobile-test/projects/new";

const session = {
  id: "22222222-2222-4222-8222-222222222222",
  user_id: "33333333-3333-4333-8333-333333333333",
  display_name: "Mobile Test User",
  email: "mobile-test@grafy.invalid",
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2030-01-01T00:00:00Z",
  last_used_at: "2026-01-01T00:00:00Z",
  revoked_at: null,
  current: true,
} satisfies Session;

const workspace = {
  id: WORKSPACE_ID,
  slug: "mobile-test",
  name: "Mobile test",
  kind: "personal",
  role: "owner",
  capabilities: [
    "view_project",
    "view_artifacts",
    "view_runs",
    "join_project_room",
    "publish_presence",
    "create_project",
    "edit_project",
    "checkpoint_project",
    "start_run",
    "cancel_run",
    "manage_secrets",
    "delete_project",
    "manage_members",
    "rename_workspace",
  ],
} satisfies Workspace;

const savedProjects = { projects: [] } satisfies ProjectList;
export const nodeRegistry = {
  artifact_conversions: [],
  artifact_types: [],
  nodes: [
    {
      operator_id: "test.text_source",
      operator_version: 1,
      plugin_slug: "builtin",
      origin: "builtin",
      title: "Test text source",
      description: "Produces text for browser interaction tests.",
      catalog_visible: true,
      runnable: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [],
      outputs: [
        {
          name: "text",
          title: "Text",
          description: "Produced text.",
          direction: "output",
          artifact_type: { id: "scalar.text", schema_version: 1 },
          artifact_type_variable: null,
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
        },
      ],
    },
    {
      operator_id: "test.text_sink",
      operator_version: 1,
      plugin_slug: "builtin",
      origin: "builtin",
      title: "Test text sink",
      description: "Accepts text for browser interaction tests.",
      catalog_visible: true,
      runnable: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [
        {
          name: "text",
          title: "Text",
          description: "Text to accept.",
          direction: "input",
          artifact_type: { id: "scalar.text", schema_version: 1 },
          artifact_type_variable: null,
          shape: "one",
          accepted_shapes: ["one"],
          instance_plugs: false,
          variadic: false,
          required: true,
        },
      ],
      outputs: [],
    },
  ],
  plugins: [
    {
      slug: "builtin",
      title: "Built-in",
      origin: "builtin",
      entry_kind: "plugin",
    },
  ],
} satisfies NodeRegistry;
const invitations: readonly WorkspaceInvitationForRecipient[] = [];

export interface GrafyApiFixtures {
  readonly onRoomSend?: (send: (message: JsonObject) => void) => void;
  readonly workspaces: readonly Workspace[];
  /** Saved Projects keyed by workspace id, the way the API addresses them. */
  readonly projectsByWorkspace: Readonly<Record<string, ProjectList>>;
  readonly registry?: NodeRegistry;
  readonly invitations?: readonly WorkspaceInvitationForRecipient[];
}

/** The one-person, one-workspace world every workbench spec already expects. */
export const workbenchApiFixtures: GrafyApiFixtures = {
  workspaces: [workspace],
  projectsByWorkspace: { [WORKSPACE_ID]: savedProjects },
  registry: nodeRegistry,
};

/**
 * `/api/v1/workspaces/{workspace_id}/{tail}` — the shape every location-scoped
 * endpoint shares, so `projects` and `nodes` are matched as siblings by one
 * read of the tail. Matching them in sequence instead lets a broad rule swallow
 * `/nodes`, and a spec then fails on a catalog that never arrived.
 */
const WORKSPACE_SCOPED = /^\/api\/v1\/workspaces\/([^/]+)\/([^/]+)$/;
/** `/api/v1/workspaces/{workspace_id}/projects/{project_id}[/tail…]` */
const PROJECT_SCOPED =
  /^\/api\/v1\/workspaces\/([^/]+)\/projects\/([^/]+)(\/.*)?$/;
/** The same Project address as the Project room holds it, on the WebSocket. */
const PROJECT_ROOM =
  /^\/api\/v1\/workspaces\/([^/]+)\/projects\/([^/]+)\/room$/;
/** The per-node secret write the Project owns. */
const NODE_SECRET =
  /^\/api\/v1\/workspaces\/[^/]+\/projects\/[^/]+\/graphs\/([^/]+)\/nodes\/([^/]+)\/secrets\/([^/]+)$/;

const FIXED_TIMESTAMP = "2026-10-07T12:00:00Z";

/** The identity the room hands this browser: one session, one actor. */
const ROOM_SESSION_ID = "44444444-4444-4444-8444-444444444444";
const ROOM_ACTOR = {
  actor_id: session.user_id,
  display_name: session.display_name,
  color: "#7c3aed",
};

type JsonObject = Record<string, unknown>;

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** One stored result, addressed by the node instance that produced it. */
interface StoredResult {
  readonly fingerprint: string;
  readonly outputs: Readonly<Record<string, ArtifactOutputValue>>;
}

interface StoredCheckpoint {
  readonly revision: number;
  readonly name: string;
  readonly head: CollaborativeHead;
}

/**
 * One Project the page created during this test, as the fixture keeps it.
 *
 * The Project head is the one stored value: a command batch advances it
 * through the app's own replay (`applyRoomCommandsToHead`), and every read —
 * head, instances, a restored checkpoint — is projected from it. Because
 * client and fixture run the same reducer over the same batch, a save the
 * page made cannot come back from the fixture disagreeing with the canvas,
 * which is how a wrongly-echoed save once made a spec test the fixture
 * instead of the app.
 */
interface MockProject {
  readonly workspaceId: string;
  readonly id: string;
  head: CollaborativeHead;
  readonly checkpoints: StoredCheckpoint[];
  readonly runs: Run[];
  /** Stored results keyed by node id — root instances only, as the canvas reads. */
  readonly results: Map<string, StoredResult>;
}

/**
 * A synthetic UUID. Every id the fixture invents (project, run, artifact) comes
 * from this one counter, so a failing spec names an id that no other source in
 * the test could have produced. The variant nibble stays inside `[89ab]` like
 * a real UUID's, because the Workbench answers an address that is not a
 * well-formed UUID with a 404 — a malformed fixture id would have the page
 * under test reject the Project the fixture itself just created.
 */
function makeIdFactory() {
  let counter = 0;
  return (prefix: "p" | "r" | "a"): string => {
    counter += 1;
    const tail = counter.toString(16).padStart(12, "0");
    const head = prefix === "p" ? "8000" : prefix === "r" ? "9000" : "b000";
    return `00000000-0000-4000-${head}-${tail}`;
  };
}

function emptyGraphDocument(): JsonObject {
  return { schema_version: 7, nodes: [], edges: [], origins: [] };
}

interface DocumentNode {
  readonly id: string;
  readonly operatorId: string;
}

function documentNodes(document: JsonObject): DocumentNode[] {
  const nodes = Array.isArray(document.nodes) ? document.nodes : [];
  const readable: DocumentNode[] = [];
  for (const node of nodes) {
    if (!isJsonObject(node) || typeof node.id !== "string") continue;
    readable.push({
      id: node.id,
      operatorId:
        typeof node.operator_id === "string" ? node.operator_id : "unknown",
    });
  }
  return readable;
}

/** The Graph a one-Graph Project holds: the first, which is what the canvas opens. */
function graphOf(project: MockProject): {
  readonly id: string;
  readonly name: string;
  readonly document: JsonObject;
} | null {
  const graphs = project.head.document.graphs;
  const first = graphs.length > 0 ? graphs[0] : undefined;
  if (first === undefined) return null;
  return {
    id: first.id,
    name: first.name,
    document: first.document as unknown as JsonObject,
  };
}

function graphIdOf(project: MockProject): string {
  return graphOf(project)?.id ?? "";
}

function nodesOf(project: MockProject): DocumentNode[] {
  const graph = graphOf(project);
  return graph === null ? [] : documentNodes(graph.document);
}

/**
 * The outputs one operator produces when a Run makes its instance fresh.
 *
 * Synthesized from the live registry rather than a per-spec stub: the fixture
 * already carries the node specs the picker offered the canvas, and a node the
 * person could add is a node whose result shape the registry already states.
 */
function outputsForOperator(
  registry: NodeRegistry | undefined,
  operatorId: string,
  nextArtifactId: () => string,
): Record<string, ArtifactOutputValue> {
  const spec = registry?.nodes.find(
    (candidate) => candidate.operator_id === operatorId,
  );
  const outputs: Record<string, ArtifactOutputValue> = {};
  for (const port of spec?.outputs ?? []) {
    outputs[port.name] = {
      artifact_id: nextArtifactId(),
      artifact_type:
        port.artifact_type?.id ?? port.artifact_type_variable ?? "scalar.text",
      schema_version: port.artifact_type?.schema_version ?? 1,
    };
  }
  return outputs;
}

function initialHead(
  projectId: string,
  name: string,
  graphId: string,
  graphName: string,
  roomEpoch: string,
): CollaborativeHead {
  return {
    project_id: projectId,
    name,
    room_epoch: roomEpoch,
    collaboration_sequence: 0,
    checkpoint_sequence: 0,
    checkpoint_revision: 0,
    updated_at: FIXED_TIMESTAMP,
    document: {
      graphs: [
        { id: graphId, name: graphName, document: emptyGraphDocument() },
      ],
    },
  } as unknown as CollaborativeHead;
}

function summaryOf(project: MockProject): ProjectSummary {
  const graph = graphOf(project);
  const nodes = graph === null ? [] : documentNodes(graph.document);
  const edges =
    graph === null || !Array.isArray(graph.document.edges)
      ? []
      : graph.document.edges;
  return {
    id: project.id,
    name: project.head.name,
    node_count: nodes.length,
    edge_count: edges.length,
    graph_count: project.head.document.graphs.length,
    revision: project.head.checkpoint_revision,
    updated_at: FIXED_TIMESTAMP,
    draft_pending:
      project.head.collaboration_sequence !== project.head.checkpoint_sequence,
  };
}

function instanceStateOf(
  project: MockProject,
  node: DocumentNode,
): InstanceState {
  const stored = project.results.get(node.id);
  return {
    key: {
      project_id: project.id,
      graph_id: graphIdOf(project),
      node_id: node.id,
      call_path: [],
    },
    // Derived the way the server derives it: an instance holds a result only
    // after a Run made it fresh, and an instance with no result is stale.
    state: stored === undefined ? "stale" : "fresh",
    fingerprint: `doc-${project.head.collaboration_sequence}`,
    last_result_fingerprint: stored?.fingerprint ?? null,
    error: null,
  };
}

/** The room's shape of the same instance state the HTTP read publishes. */
function roomInstanceOf(project: MockProject, node: DocumentNode): JsonObject {
  const stored = project.results.get(node.id);
  return {
    project_id: project.id,
    graph_id: graphIdOf(project),
    call_path: [],
    node_id: node.id,
    map_index: null,
    state: stored === undefined ? "stale" : "fresh",
    fingerprint: `doc-${project.head.collaboration_sequence}`,
    last_result_fingerprint: stored?.fingerprint ?? null,
    error: null,
  };
}

function activeRunOf(run: Run): ActiveRunSummary {
  return {
    run_id: run.id,
    graph_id: run.graph_id,
    targets: run.targets,
    starter: null,
    started_at: run.created_at,
    cancellable: true,
  };
}

interface Answer {
  readonly status: number;
  readonly json: unknown;
}

const ok = (json: unknown): Answer => ({ status: 200, json });

/**
 * The fixture's Project surface, one per mocked page: created Projects, what
 * Runs stored on their instances, and the open Project-room sockets all live
 * only as long as the page does.
 */
function projectWorld(fixtures: GrafyApiFixtures) {
  const projects = new Map<string, MockProject>();
  const nextId = makeIdFactory();
  const registry = fixtures.registry;
  /** Open room sockets by Project id: the browser keeps exactly one per page. */
  const roomSockets = new Map<string, Set<(message: JsonObject) => void>>();

  function sendToRoom(projectId: string, message: JsonObject): void {
    for (const send of roomSockets.get(projectId) ?? []) send(message);
  }

  /**
   * Advance one Project by one accepted command batch.
   *
   * The replay is the app's own: the same reducer the room session runs when a
   * batch comes back accepted. Client and fixture therefore land on the same
   * head from the same batch, which is the only way a mocked server can let a
   * spec assert that a draft saved cleanly.
   */
  function applyCommandBatch(
    record: MockProject,
    body: unknown,
  ): { readonly sequence: number; readonly commandId: string } | null {
    if (!isJsonObject(body) || !Array.isArray(body.commands)) return null;
    const sequence = record.head.collaboration_sequence + 1;
    record.head = applyRoomCommandsToHead(
      record.head,
      body.commands as readonly RoomProjectCommand[],
      sequence,
    );
    return {
      sequence,
      commandId: typeof body.command_id === "string" ? body.command_id : "",
    };
  }

  function handleGet(
    path: string,
    params: URLSearchParams,
  ): Answer | undefined {
    if (path === "/api/v1/auth/session") return ok(session);
    if (path === "/api/v1/workspaces") return ok(fixtures.workspaces);
    if (path === "/api/v1/me/invitations")
      return ok(fixtures.invitations ?? invitations);

    if (path === "/api/v1/me/projects") {
      // The cross-workspace feed every discovery surface shares. The fixture
      // world has one Workspace per listed Project, so `location` names it.
      const items = [...projects.values()].map((project) => {
        const host = fixtures.workspaces.find(
          (candidate) => candidate.id === project.workspaceId,
        );
        if (host === undefined) return null;
        return {
          ...summaryOf(project),
          archived: false,
          archived_at: null,
          creator: null,
          folder: null,
          last_opened_at: null,
          starred: false,
          location: {
            id: host.id,
            kind: host.kind,
            name: host.name,
            slug: host.slug,
          },
        };
      });
      return ok({ projects: items.filter((item) => item !== null) });
    }

    const scoped = path.match(WORKSPACE_SCOPED);
    const workspaceId = scoped?.[1];
    const tail = scoped?.[2];
    if (workspaceId !== undefined && tail !== undefined) {
      // A saved graph's own document (`/graphs/{graph_id}`) is deliberately not
      // here: these specs author drafts, and a spec that starts opening one
      // should see a 501 rather than a blank canvas it mistakes for the app
      // being broken.
      if (tail === "nodes") return ok(fixtures.registry ?? null);
      if (tail === "projects") return ok(projectsListFor(workspaceId));
      return undefined;
    }

    const project = matchProject(path);
    if (!project) return undefined;
    const route = project.route;

    if (route === "" || route === "/") {
      return ok({
        id: project.record.id,
        name: project.record.head.name,
        created_at: FIXED_TIMESTAMP,
        updated_at: FIXED_TIMESTAMP,
      });
    }
    if (route === "/head") return ok(project.record.head);
    if (route === "/checkpoints") {
      return ok({
        checkpoints: project.record.checkpoints.map((checkpoint) => ({
          revision: checkpoint.revision,
          name: checkpoint.name,
          created_at: FIXED_TIMESTAMP,
        })),
      });
    }
    const checkpoint = route.match(/^\/checkpoints\/(\d+)$/)?.[1];
    if (checkpoint !== undefined) {
      const wanted = project.record.checkpoints.find(
        (candidate) => candidate.revision === Number(checkpoint),
      );
      if (wanted === undefined) return undefined;
      return ok({
        revision: wanted.revision,
        name: wanted.name,
        created_at: FIXED_TIMESTAMP,
        document: wanted.head.document,
      });
    }
    if (route === "/runs") {
      const active = params.get("active");
      const runs =
        active === "true"
          ? project.record.runs.filter(
              (run) =>
                run.status !== "succeeded" &&
                run.status !== "failed" &&
                run.status !== "cancelled" &&
                run.status !== "interrupted",
            )
          : project.record.runs;
      return ok({ runs });
    }
    const runId = route.match(/^\/runs\/([^/]+)$/)?.[1];
    if (runId !== undefined) {
      const run = project.record.runs.find(
        (candidate) => candidate.id === runId,
      );
      return run ? ok(run) : undefined;
    }
    const instances = route.match(/^\/graphs\/([^/]+)\/instances$/);
    if (instances?.[1] === graphIdOf(project.record)) {
      return ok({
        instances: nodesOf(project.record).map((node) =>
          instanceStateOf(project.record, node),
        ),
      });
    }
    if (route === "/instance-result") {
      return ok(instanceResultOf(project.record, params));
    }
    if (route === "/node-secrets") {
      return ok({
        graph_id: params.get("graph_id") ?? graphIdOf(project.record),
        head_sequence: project.record.head.collaboration_sequence,
        project_id: project.record.id,
        secrets: [],
        unresolved_nodes: [],
      });
    }
    return undefined;
  }

  /** The workspace's list: what the fixture seeded, plus what this page made. */
  function projectsListFor(workspaceId: string): ProjectList | undefined {
    const seeded = fixtures.projectsByWorkspace[workspaceId];
    if (seeded === undefined) return undefined;
    const created = [...projects.values()]
      .filter((project) => project.workspaceId === workspaceId)
      .map(summaryOf);
    return { projects: [...seeded.projects, ...created] };
  }

  function instanceResultOf(
    project: MockProject,
    params: URLSearchParams,
  ): InstanceResult | undefined {
    const nodeId = params.get("node_id");
    const graphId = params.get("graph_id");
    if (nodeId === null || graphId !== graphIdOf(project)) return undefined;
    // A result travels with its instance; the call path only addresses nested
    // instances, and the canvas never reads those here.
    if (params.getAll("call_path").length > 0) return undefined;
    const node = nodesOf(project).find((candidate) => candidate.id === nodeId);
    if (node === undefined) return undefined;
    const instance = instanceStateOf(project, node);
    const stored = project.results.get(nodeId);
    return {
      instance,
      outputs: stored?.outputs ?? null,
      result_fingerprint: stored?.fingerprint ?? null,
      created_at: stored === undefined ? null : FIXED_TIMESTAMP,
    };
  }

  function handlePost(path: string, body: unknown): Answer | undefined | null {
    const created = path.match(/^\/api\/v1\/workspaces\/([^/]+)\/projects$/);
    const workspaceId = created?.[1];
    if (workspaceId !== undefined) {
      if (fixtures.projectsByWorkspace[workspaceId] === undefined) {
        return undefined;
      }
      if (!isJsonObject(body)) return null;
      const graphId = typeof body.graph_id === "string" ? body.graph_id : "";
      const projectId =
        typeof body.project_id === "string" && body.project_id
          ? body.project_id
          : nextId("p");
      const record: MockProject = {
        workspaceId,
        id: projectId,
        head: initialHead(
          projectId,
          typeof body.name === "string" ? body.name : "Untitled",
          graphId,
          typeof body.graph_name === "string" ? body.graph_name : "",
          "11111111-0000-4000-8000-000000000001",
        ),
        checkpoints: [],
        runs: [],
        results: new Map(),
      };
      projects.set(record.id, record);
      return ok({
        id: record.id,
        name: record.head.name,
        created_at: FIXED_TIMESTAMP,
        updated_at: FIXED_TIMESTAMP,
      });
    }

    const project = matchProject(path);
    if (!project) return undefined;
    const { record, route } = project;

    if (route === "/commands") {
      const applied = applyCommandBatch(record, body);
      if (applied === null) return null;
      return ok({
        head: record.head,
        receipt: {
          accepted_sequence: applied.sequence,
          command_id: applied.commandId,
          deduplicated: false,
          outcome: "accepted",
          room_epoch: record.head.room_epoch,
        },
      });
    }

    if (route === "/checkpoints") return ok(checkpoint(record));
    const restore = route.match(/^\/checkpoints\/(\d+)\/restore$/)?.[1];
    if (restore !== undefined) {
      const wanted = record.checkpoints.find(
        (candidate) => candidate.revision === Number(restore),
      );
      if (wanted === undefined) return undefined;
      // Bringing a checkpoint forward appends a newer one; history never rewinds.
      record.head = wanted.head;
      return ok(checkpoint(record));
    }
    if (route === "/opened") return ok(null);

    if (route === "/runs") {
      if (!isJsonObject(body) || !Array.isArray(body.targets)) return null;
      const targets = body.targets.filter(isJsonObject).map((target) => ({
        node_id: typeof target.node_id === "string" ? target.node_id : "",
        call_path: Array.isArray(target.call_path)
          ? target.call_path.filter(
              (segment): segment is string => typeof segment === "string",
            )
          : [],
      }));
      const graphId =
        typeof body.graph_id === "string" ? body.graph_id : graphIdOf(record);
      const run: Run = {
        id: nextId("r"),
        project_id: record.id,
        workspace_id: record.workspaceId,
        graph_id: graphId,
        status: "succeeded",
        error: null,
        targets,
        started_by_user_id: null,
        created_at: FIXED_TIMESTAMP,
        finished_at: FIXED_TIMESTAMP,
      };
      record.runs.push(run);
      // The Run's demand is settled the moment it is made here: every target
      // instance becomes fresh and stores the result its operator produces.
      const freshNodes: DocumentNode[] = [];
      for (const target of targets) {
        const node = nodesOf(record).find(
          (candidate) => candidate.id === target.node_id,
        );
        if (node === undefined) continue;
        record.results.set(node.id, {
          fingerprint: `res-${node.id}-${record.results.size + 1}`,
          outputs: outputsForOperator(registry, node.operatorId, () =>
            nextId("a"),
          ),
        });
        freshNodes.push(node);
      }
      // What a real room would push for a Run that finishes this fast. The
      // run surface reads either way — the pushes are what make a spec prove
      // the room's signal, rather than only its fallback.
      if (roomSockets.has(record.id)) {
        sendToRoom(record.id, {
          protocol_version: 1,
          type: "run.started",
          run: activeRunOf(run),
        });
        sendToRoom(record.id, {
          protocol_version: 1,
          type: "run.finished",
          run_id: run.id,
          status: "succeeded",
          error: null,
        });
        sendToRoom(record.id, {
          protocol_version: 1,
          type: "instances.changed",
          changed: freshNodes.map((node) => roomInstanceOf(record, node)),
          removed: [],
          head_sequence: record.head.collaboration_sequence,
        });
      }
      return ok(run);
    }

    const cancel = route.match(/^\/runs\/([^/]+)\/cancel$/)?.[1];
    if (cancel !== undefined) {
      const run = record.runs.find((candidate) => candidate.id === cancel);
      return run ? ok(run) : undefined;
    }
    return undefined;
  }

  function checkpoint(record: MockProject): JsonObject {
    record.head = {
      ...record.head,
      checkpoint_sequence: record.head.collaboration_sequence,
      checkpoint_revision: record.head.checkpoint_revision + 1,
    };
    record.checkpoints.push({
      revision: record.head.checkpoint_revision,
      name: record.head.name,
      head: record.head,
    });
    return {
      checkpoint_revision: record.head.checkpoint_revision,
      head: record.head,
    };
  }

  function matchProject(path: string) {
    const match = path.match(PROJECT_SCOPED);
    const workspaceId = match?.[1];
    const projectId = match?.[2];
    if (!match || workspaceId === undefined || projectId === undefined) {
      return null;
    }
    const record = projects.get(projectId);
    if (record === undefined || record.workspaceId !== workspaceId) return null;
    return { record, route: match[3] ?? "" };
  }

  function handlePut(path: string, body: unknown): Answer | undefined | null {
    const secret = path.match(NODE_SECRET);
    const project = matchProject(path);
    if (secret && project) {
      const [, graphId, nodeId, name] = secret;
      if (
        graphId !== graphIdOf(project.record) ||
        !nodesOf(project.record).some((node) => node.id === nodeId)
      ) {
        return undefined;
      }
      return ok({
        configured: true,
        name: decodeURIComponent(name ?? ""),
        node_id: nodeId,
      });
    }
    if (project && (project.route === "/star" || project.route === "/folder")) {
      if (project.route === "/folder" && !isJsonObject(body)) return null;
      if (project.route === "/folder") {
        return ok({
          archived: false,
          archived_at: null,
          folder_id:
            isJsonObject(body) && typeof body.folder_id === "string"
              ? body.folder_id
              : null,
          project_id: project.record.id,
          starred: false,
        });
      }
      return ok(null);
    }
    return undefined;
  }

  function handleDelete(path: string): Answer | undefined {
    const secret = path.match(NODE_SECRET);
    const project = matchProject(path);
    if (secret && project) return ok(null);
    if (project) {
      if (project.route === "/star" || project.route === "/archive") {
        return ok(null);
      }
      if (project.route === "") {
        projects.delete(project.record.id);
        return ok(null);
      }
    }
    return undefined;
  }

  /**
   * Answer one browser connection to a Project room.
   *
   * `room.ready` carries the head, the capabilities, and the instance states as
   * the world holds them at that moment, so a page that connects after a save
   * reads its own saved document back, exactly as it would from the real
   * server. Command batches run through the same `applyCommandBatch` the HTTP
   * fallback uses and are answered with the `accepted` + `receipt` pair the
   * client's outbox waits for. Presence traffic is accepted and ignored: one
   * browser is the whole room here.
   */
  function routeProjectRoom(connection: WebSocketRoute): void {
    const url = new URL(connection.url());
    const match = url.pathname.match(PROJECT_ROOM);
    const workspaceId = match?.[1];
    const projectId = match?.[2];
    const record =
      projectId === undefined ? undefined : projects.get(projectId);
    if (
      record === undefined ||
      workspaceId === undefined ||
      record.workspaceId !== workspaceId
    ) {
      // A room for a Project this world does not hold is the same fact the
      // HTTP surface reports about such an id: it is not here. 4004 is the
      // protocol's access-revoked close, which stops the client retrying.
      void connection.close({ code: 4004, reason: "project_unknown" });
      return;
    }

    const send = (message: JsonObject): void => {
      // A page can navigate away between one world event and its delivery;
      // a dead socket is not an error, it is a room nobody is listening to.
      void Promise.resolve(connection.send(JSON.stringify(message))).catch(
        () => undefined,
      );
    };
    let sockets = roomSockets.get(record.id);
    if (sockets === undefined) {
      sockets = new Set();
      roomSockets.set(record.id, sockets);
    }
    sockets.add(send);
    fixtures.onRoomSend?.(send);
    connection.onClose(() => sockets.delete(send));

    send({
      protocol_version: 1,
      type: "room.ready",
      workspace_id: record.workspaceId,
      project_id: record.id,
      project_room_session_id: ROOM_SESSION_ID,
      actor: ROOM_ACTOR,
      capabilities: {
        capabilities:
          fixtures.workspaces.find(
            (candidate) => candidate.id === record.workspaceId,
          )?.capabilities ?? [],
        authorization_version: 1,
      },
      head: record.head,
      participants: [],
      active_runs: record.runs
        .filter(
          (run) =>
            run.status !== "succeeded" &&
            run.status !== "failed" &&
            run.status !== "cancelled" &&
            run.status !== "interrupted",
        )
        .map(activeRunOf),
      instances: nodesOf(record).map((node) => roomInstanceOf(record, node)),
      registry_marker: "playwright-fixture",
    });

    connection.onMessage((raw) => {
      let message: unknown;
      try {
        message = JSON.parse(String(raw));
      } catch {
        return;
      }
      if (!isJsonObject(message)) return;
      if (message.type !== "project.command.submit") return;
      const applied = applyCommandBatch(record, message);
      if (applied === null) return;
      send({
        protocol_version: 1,
        type: "project.command.accepted",
        command_id: applied.commandId,
        room_epoch: record.head.room_epoch,
        sequence: applied.sequence,
        actor: ROOM_ACTOR,
        project_room_session_id: ROOM_SESSION_ID,
        commands: message.commands,
      });
      send({
        protocol_version: 1,
        type: "project.command.receipt",
        command_id: applied.commandId,
        outcome: "accepted",
        accepted_room_epoch: record.head.room_epoch,
        accepted_sequence: applied.sequence,
        current_room_epoch: record.head.room_epoch,
        current_sequence: applied.sequence,
        deduplicated: false,
        requires_head_rehydration: false,
      });
    });
  }

  return {
    answer(
      method: string,
      path: string,
      params: URLSearchParams,
      body: unknown,
    ): Answer | undefined {
      let result: Answer | undefined | null;
      if (method === "GET") result = handleGet(path, params);
      else if (method === "POST") result = handlePost(path, body);
      else if (method === "PUT") result = handlePut(path, body);
      else if (method === "DELETE") result = handleDelete(path);
      else result = undefined;
      // `null` means the route matched but the request had no usable body.
      return result === null ? ok(null) : result;
    },
    routeProjectRoom,
  };
}

/**
 * Answer the endpoints the web app calls, and hand back a reader for anything
 * this fixture did not cover. A spec that starts asking for an endpoint it was
 * not given sees a 501 and a non-empty list instead of a silent hole.
 *
 * Project reads and writes and the Project room are answered by one per-page
 * world: a saved graph is head, commands, and checkpoints on the wire, so the
 * fixture has to remember what it was told. The room arrives on a WebSocket,
 * which `page.route` does not intercept — `page.routeWebSocket` does — and the
 * world above answers it with the same head the HTTP reads return, so a
 * room-driven Run, `instances.changed`, and command round trip are all in
 * scope for a spec here.
 */
export async function mockGrafyApi(
  page: Page,
  fixtures: GrafyApiFixtures = workbenchApiFixtures,
): Promise<() => readonly string[]> {
  const unhandledApiRequests: string[] = [];
  const world = projectWorld(fixtures);

  // Registered before any navigation: a routed WebSocket only covers
  // connections opened after the route was in place.
  await page.routeWebSocket(
    /\/api\/v1\/workspaces\/[^/]+\/projects\/[^/]+\/room$/,
    (route) => world.routeProjectRoom(route),
  );

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    let body: unknown;
    if (method !== "GET" && method !== "DELETE") {
      try {
        body = await request.postDataJSON();
      } catch {
        body = undefined;
      }
    }

    const answer = world.answer(method, path, url.searchParams, body);
    if (answer !== undefined) {
      await route.fulfill({ status: answer.status, json: answer.json });
      return;
    }

    const unhandledRequest = `${method} ${path}`;
    unhandledApiRequests.push(unhandledRequest);
    await route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({
        detail: `Unhandled Playwright API fixture: ${unhandledRequest}`,
      }),
    });
  });

  return () => unhandledApiRequests;
}

export const test = base.extend<{
  registry: NodeRegistry;
  agentRoom: { send?: (message: JsonObject) => void };
}>({
  agentRoom: async ({}, provide) => {
    await provide({});
  },
  registry: [nodeRegistry, { option: true }],
  page: async ({ page, registry, agentRoom }, runTest) => {
    const unhandled = await mockGrafyApi(page, {
      ...workbenchApiFixtures,
      onRoomSend: (send) => {
        agentRoom.send = send;
      },
      registry,
    });

    // The Library folder tree is the server's now, so every workbench test needs
    // it: the panel lists it on open and an artifact card reads its path from it.
    // Registered after the catch-all above, so these routes win for /library.
    await libraryStub(page);

    await page.goto(WORKBENCH_PATH);
    await expect(page.locator(".react-flow")).toBeVisible();
    await runTest(page);
    expect(unhandled(), "Unhandled Playwright API requests").toEqual([]);
  },
});

export { expect };
