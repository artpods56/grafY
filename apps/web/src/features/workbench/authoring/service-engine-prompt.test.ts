import { describe, expect, it } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { runEffectReducer } from "@/lib/state/effect-reducer";

import {
  DEFAULT_NODE_PLACEMENT_HEIGHT,
  DEFAULT_NODE_WIDTH,
  SERVICE_PROVIDER_GAP,
} from "./node-layout";
import {
  initialServiceEnginePromptState,
  serviceEnginePromptReducer,
  type ServiceEngineConsumer,
  type ServiceEngineDraftIds,
  type ServiceEnginePromptAction,
  type ServiceEnginePromptEffect,
  type ServiceEnginePromptState,
  type ServiceEngineVault,
  type ServiceEngineWorld,
} from "./service-engine-prompt";
import {
  artifactPortFixture,
  nodeSpecFixture,
  servicePortFixture,
} from "../test-fixtures";

const contract = { id: "ocr.document", version: 1 };
const IDLE = initialServiceEnginePromptState();
const DRAFTS: ServiceEngineDraftIds = {
  nodeId: "node-provider",
  edgeId: "edge-provider",
};
const POSITION = { x: 480, y: 160 };

function enginePort(
  name: string,
  direction: Port["direction"],
  title: string,
  features?: readonly string[],
): Port {
  return servicePortFixture({
    name,
    title,
    direction,
    required: true,
    service_contracts: [contract],
    service_features: features ? [{ contract, features: [...features] }] : [],
  });
}

function featureOutput(name: string, title: string, feature: string): Port {
  return artifactPortFixture({
    name,
    title,
    direction: "output",
    required: false,
    requires_service_feature: { input_port: "engine", feature },
  });
}

function secretInput(providerKind: string) {
  return {
    name: "api_key",
    title: "API key",
    config_dependencies: [],
    provider_kind: providerKind,
    supports_verification: false,
  };
}

function providerSpec(
  id: string,
  title: string,
  features: readonly string[],
  options: Partial<NodeSpec> = {},
): NodeSpec {
  return nodeSpecFixture({
    operator_id: id,
    title,
    description: `${title} reads a page.`,
    plugin_slug: "ocr",
    outputs: [enginePort("ocr", "output", title, features)],
    ...options,
  });
}

const documentOcr = nodeSpecFixture({
  operator_id: "ocr.read_document",
  title: "Document OCR",
  description: "Read a scan.",
  plugin_slug: "ocr",
  inputs: [enginePort("engine", "input", "OCR engine")],
  outputs: [
    featureOutput("blocks", "Text blocks", "blocks"),
    featureOutput("boxes", "Boxes on the page", "regions"),
  ],
});

const mistral = providerSpec("mistral.ocr", "Mistral OCR", [
  "blocks",
  "regions",
]);
const reducto = providerSpec("reducto.ocr", "Reducto", ["blocks"], {
  secret_inputs: [secretInput("reducto")],
});
const localEngine = providerSpec("local.ocr", "Local OCR", [
  "blocks",
  "regions",
]);
const hidden = providerSpec("hidden.ocr", "Hidden OCR", ["blocks", "regions"], {
  catalog_visible: false,
});

function registryOf(nodes: readonly NodeSpec[]): NodeRegistry {
  return {
    packs: [],
    plugins: [
      {
        slug: "ocr",
        title: "OCR",
        origin: "builtin",
        entry_kind: "plugin",
      },
    ],
    artifact_types: [],
    artifact_conversions: [],
    nodes: [...nodes],
  };
}

function vault(
  overrides: Partial<ServiceEngineVault> = {},
): ServiceEngineVault {
  return {
    canEditProject: true,
    credentials: [],
    deploymentDefaults: [],
    ...overrides,
  };
}

function world(
  nodes: readonly NodeSpec[],
  vaultOverrides: Partial<ServiceEngineVault> = {},
): ServiceEngineWorld {
  return {
    registry: registryOf(nodes),
    catalogNodes: nodes,
    vault: vault(vaultOverrides),
  };
}

function consumer(
  spec: NodeSpec = documentOcr,
  satisfiedInputs: readonly string[] = [],
  position = POSITION,
): ServiceEngineConsumer {
  return { id: "node-ocr", position, spec, satisfiedInputs };
}

function place(
  origin: "node_selector" | "continue_from_port" = "node_selector",
  next: ServiceEngineConsumer = consumer(),
  gates: { canEdit?: boolean; running?: boolean; graphId?: string } = {},
): ServiceEnginePromptAction {
  return {
    type: "local_placement",
    origin,
    graphId: gates.graphId ?? "graph-1",
    canEdit: gates.canEdit ?? true,
    running: gates.running ?? false,
    consumer: next,
  };
}

function commit(
  state: ServiceEnginePromptState,
  next: ServiceEngineConsumer | null,
  scene: ServiceEngineWorld | null,
  gates: { canEdit?: boolean; running?: boolean; graphId?: string } = {},
): ServiceEnginePromptAction {
  return {
    type: "placement_committed",
    graphId:
      gates.graphId ?? (state.phase === "idle" ? "graph-1" : state.graphId),
    canEdit: gates.canEdit ?? true,
    running: gates.running ?? false,
    consumer: next,
    world: scene,
    draftIds: DRAFTS,
  };
}

function step(
  state: ServiceEnginePromptState,
  action: ServiceEnginePromptAction,
) {
  return runEffectReducer(serviceEnginePromptReducer, state, action);
}

function connectOf(effects: readonly ServiceEnginePromptEffect[]) {
  const effect = effects.find(
    (candidate) => candidate.type === "connect_provider",
  );
  if (!effect || effect.type !== "connect_provider") {
    throw new Error("expected a connect effect");
  }
  return effect;
}

function openOf(effects: readonly ServiceEnginePromptEffect[]) {
  const effect = effects.find((candidate) => candidate.type === "open_prompt");
  if (!effect || effect.type !== "open_prompt") {
    throw new Error("expected an open effect");
  }
  return effect;
}

describe("service engine prompt", () => {
  it("ignores a committed node that no local gesture placed", () => {
    const scene = world([mistral]);
    const result = step(IDLE, commit(IDLE, consumer(), scene));
    expect(result.state).toBe(IDLE);
    expect(result.effects).toEqual([]);
  });

  it("stays idle when editing is closed, a run is active, or the graph id is empty", () => {
    const scene = world([mistral]);
    for (const gates of [
      { canEdit: false },
      { running: true },
      { graphId: "" },
    ]) {
      const armed = step(IDLE, place("node_selector", consumer(), gates));
      expect(armed.state).toBe(IDLE);
      expect(armed.effects).toEqual([]);
      const picked = step(IDLE, {
        type: "pick_engine",
        graphId: gates.graphId ?? "graph-1",
        canEdit: gates.canEdit ?? true,
        running: gates.running ?? false,
        consumer: consumer(),
        portName: "engine",
        world: scene,
        draftIds: DRAFTS,
      });
      expect(picked.state).toBe(IDLE);
      expect(picked.effects).toEqual([]);
    }
  });

  it("does not arm a node whose service input is already satisfied", () => {
    const satisfied = step(
      IDLE,
      place("continue_from_port", consumer(documentOcr, ["engine"])),
    );
    expect(satisfied.state).toBe(IDLE);
    const plain = step(
      IDLE,
      place(
        "node_selector",
        consumer(nodeSpecFixture({ operator_id: "note.pad", title: "Note" })),
      ),
    );
    expect(plain.state).toBe(IDLE);
  });

  it("arms the first unsatisfied required service input and waits for the commit", () => {
    const second = enginePort("backup", "input", "Backup engine");
    const spec = nodeSpecFixture({
      ...documentOcr,
      inputs: [documentOcr.inputs[0]!, second],
    });
    const armed = step(IDLE, place("node_selector", consumer(spec)));
    expect(armed.state).toEqual({
      phase: "awaiting_placement",
      graphId: "graph-1",
      consumerNodeId: "node-ocr",
      servicePortName: "engine",
      consumerPosition: POSITION,
    });
    expect(armed.effects).toEqual([]);
  });

  it("drops the wait when the graph, edit right, or run changes before commit", () => {
    const armed = step(IDLE, place()).state;
    expect(
      step(armed, {
        type: "gates",
        graphId: "graph-1",
        canEdit: true,
        running: false,
      }).state,
    ).toBe(armed);
    expect(
      step(armed, {
        type: "gates",
        graphId: "other",
        canEdit: true,
        running: false,
      }).state,
    ).toEqual({ phase: "idle" });
    expect(
      step(armed, {
        type: "gates",
        graphId: "graph-1",
        canEdit: false,
        running: false,
      }).state.phase,
    ).toBe("idle");
    expect(
      step(armed, {
        type: "gates",
        graphId: "graph-1",
        canEdit: true,
        running: true,
      }).state.phase,
    ).toBe("idle");
    expect(step(armed, commit(armed, null, world([mistral]))).state.phase).toBe(
      "idle",
    );
  });

  it("waits to decide until the catalog world exists", () => {
    const armed = step(IDLE, place()).state;
    const waiting = step(armed, commit(armed, consumer(), null));
    expect(waiting.state).toBe(armed);
    expect(waiting.effects).toEqual([]);
  });

  it("stays idle and opens nothing when no visible provider can feed the port", () => {
    const armed = step(IDLE, place()).state;
    const hiddenOnly = step(armed, commit(armed, consumer(), world([hidden])));
    expect(hiddenOnly.state).toEqual({ phase: "idle" });
    expect(hiddenOnly.effects).toEqual([]);
  });

  it("auto-connects one local provider to the left of the port and keeps the consumer selected", () => {
    const armed = step(IDLE, place("continue_from_port")).state;
    const result = step(armed, commit(armed, consumer(), world([localEngine])));
    const effect = connectOf(result.effects);
    expect(result.state).toEqual({ phase: "idle" });
    expect(effect.selectNodeId).toBe("node-ocr");
    expect(effect.toast).toBe("Connected Local OCR");
    expect(effect.undoNodeId).toBe("node-provider");
    expect(effect.bindings).toEqual([]);
    expect(effect.commands.map((command) => command.kind)).toEqual([
      "add_node",
      "add_edge",
    ]);
    const node = effect.commands[0];
    const edge = effect.commands[1];
    if (node?.kind !== "add_node" || edge?.kind !== "add_edge") {
      throw new Error("expected add_node then add_edge");
    }
    expect(node.node.position).toEqual({
      x: POSITION.x - DEFAULT_NODE_WIDTH - SERVICE_PROVIDER_GAP,
      y: POSITION.y,
    });
    expect(node.node.id).toBe("node-provider");
    expect(edge.edge).toMatchObject({
      id: "edge-provider",
      from_node: "node-provider",
      to_node: "node-ocr",
      to_port: "engine",
    });
  });

  it("auto-binds the single shared workspace key and names it in the notice", () => {
    const armed = step(IDLE, place()).state;
    const result = step(
      armed,
      commit(
        armed,
        consumer(),
        world([reducto], {
          credentials: [
            {
              id: "cred-1",
              label: "Team Reducto",
              providerKind: "reducto",
              scope: "shared",
            },
          ],
        }),
      ),
    );
    const effect = connectOf(result.effects);
    expect(effect.selectNodeId).toBe("node-ocr");
    expect(effect.toast).toBe(
      "Connected Reducto using workspace key 'Team Reducto'",
    );
    expect(effect.bindings).toEqual([
      {
        secretName: "api_key",
        credentialId: "cred-1",
        label: "Team Reducto",
      },
    ]);
  });

  it("auto-connects a deployment default without writing a shared binding", () => {
    const armed = step(IDLE, place()).state;
    const result = step(
      armed,
      commit(
        armed,
        consumer(),
        world([reducto], {
          canEditProject: false,
          deploymentDefaults: [
            { operatorId: "reducto.ocr", secretName: "api_key" },
          ],
        }),
      ),
    );
    const effect = connectOf(result.effects);
    expect(effect.bindings).toEqual([]);
    expect(effect.toast).toBe("Connected Reducto");
    expect(effect.selectNodeId).toBe("node-ocr");
  });

  it("opens the picker when the only provider is not unambiguously bindable", () => {
    const cases: Array<{
      vault: Partial<ServiceEngineVault>;
      readiness: string;
    }> = [
      { vault: {}, readiness: "Needs API key" },
      {
        vault: {
          credentials: [
            {
              id: "mine",
              label: "Mine",
              providerKind: "reducto",
              scope: "personal",
            },
          ],
        },
        readiness: "Personal key available",
      },
      {
        vault: {
          credentials: [
            {
              id: "a",
              label: "A",
              providerKind: "reducto",
              scope: "shared",
            },
            {
              id: "b",
              label: "B",
              providerKind: "reducto",
              scope: "shared",
            },
          ],
        },
        readiness: "Workspace key ready",
      },
      {
        vault: {
          canEditProject: false,
          credentials: [
            {
              id: "a",
              label: "A",
              providerKind: "reducto",
              scope: "shared",
            },
          ],
        },
        readiness: "Workspace key ready",
      },
    ];
    for (const entry of cases) {
      const armed = step(IDLE, place()).state;
      const result = step(
        armed,
        commit(armed, consumer(), world([reducto], entry.vault)),
      );
      const effect = openOf(result.effects);
      expect(result.state.phase).toBe("prompting");
      expect(effect.portTitle).toBe("OCR engine");
      expect(effect.flowPosition).toEqual({
        x: POSITION.x - DEFAULT_NODE_WIDTH - SERVICE_PROVIDER_GAP,
        y: POSITION.y + DEFAULT_NODE_PLACEMENT_HEIGHT / 2,
      });
      expect(effect.rows["reducto.ocr@1"]).toMatchObject({
        readiness: entry.readiness,
        pills: ["Text blocks"],
      });
    }
  });

  it("opens the picker for two visible providers and ignores a hidden third", () => {
    const armed = step(IDLE, place()).state;
    const result = step(
      armed,
      commit(armed, consumer(), world([mistral, reducto, hidden])),
    );
    const effect = openOf(result.effects);
    expect(effect.candidates.map((candidate) => candidate.spec.title)).toEqual([
      "Mistral OCR",
      "Reducto",
    ]);
    expect(effect.rows["mistral.ocr@1"]).toEqual({
      pills: ["Text blocks", "Boxes on the page"],
      readiness: "Ready (local)",
    });
    expect(effect.rows["reducto.ocr@1"]?.readiness).toBe("Needs API key");
  });

  it("formats a feature the consumer does not title", () => {
    const extra = providerSpec("extra.ocr", "Extra OCR", ["line_items"]);
    const armed = step(IDLE, place()).state;
    const result = step(
      armed,
      commit(armed, consumer(), world([mistral, extra])),
    );
    expect(openOf(result.effects).rows["extra.ocr@1"]?.pills).toEqual([
      "Line items",
    ]);
  });

  it("places the picked provider, binds its one shared key, and selects it while a key is still missing", () => {
    const both = providerSpec("split.ocr", "Split OCR", ["blocks"], {
      secret_inputs: [
        secretInput("reducto"),
        {
          name: "backup_key",
          title: "Backup key",
          config_dependencies: [],
          provider_kind: "backup",
          supports_verification: false,
        },
      ],
    });
    const scene = world([mistral, both], {
      credentials: [
        {
          id: "cred-1",
          label: "Team Reducto",
          providerKind: "reducto",
          scope: "shared",
        },
      ],
    });
    const opened = step(
      step(IDLE, place()).state,
      commit(step(IDLE, place()).state, consumer(), scene),
    );
    const prompting = step(IDLE, place()).state;
    const openedOnce = step(prompting, commit(prompting, consumer(), scene));
    expect(openedOnce.state.phase).toBe("prompting");
    const candidate = openOf(openedOnce.effects).candidates.find(
      (entry) => entry.spec.operator_id === "split.ocr",
    );
    const choice = candidate?.choices[0];
    if (!candidate || !choice) throw new Error("missing split provider");
    const chosen = step(openedOnce.state, {
      type: "provider_chosen",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      spec: candidate.spec,
      choice,
      world: scene,
      draftIds: DRAFTS,
    });
    const effect = connectOf(chosen.effects);
    expect(chosen.effects[0]?.type).toBe("close_prompt");
    expect(chosen.state).toEqual({ phase: "idle" });
    expect(effect.bindings).toEqual([
      {
        secretName: "api_key",
        credentialId: "cred-1",
        label: "Team Reducto",
      },
    ]);
    expect(effect.selectNodeId).toBe("node-provider");
    expect(opened.state.phase).toBe("prompting");
  });

  it("selects a picked provider that still needs required configuration", () => {
    const configured = providerSpec("local.ocr", "Local OCR", ["blocks"], {
      config_schema: {
        type: "object",
        required: ["region"],
        properties: { region: { type: "string" } },
      },
    });
    const scene = world([mistral, configured]);
    const prompting = step(
      step(IDLE, place()).state,
      commit(step(IDLE, place()).state, consumer(), scene),
    );
    const candidate = openOf(prompting.effects).candidates.find(
      (entry) => entry.spec.operator_id === "local.ocr",
    );
    const choice = candidate?.choices[0];
    if (!candidate || !choice || prompting.state.phase !== "prompting") {
      throw new Error("picker did not open");
    }
    const chosen = step(prompting.state, {
      type: "provider_chosen",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      spec: candidate.spec,
      choice,
      world: scene,
      draftIds: DRAFTS,
    });
    expect(connectOf(chosen.effects).selectNodeId).toBe("node-provider");
    expect(connectOf(chosen.effects).toast).toBe("Connected Local OCR");
  });

  it("keeps the consumer selected when the picked provider is ready to run", () => {
    const scene = world([mistral, reducto]);
    const prompting = step(
      step(IDLE, place()).state,
      commit(step(IDLE, place()).state, consumer(), scene),
    );
    const candidate = openOf(prompting.effects).candidates.find(
      (entry) => entry.spec.operator_id === "mistral.ocr",
    );
    const choice = candidate?.choices[0];
    if (!candidate || !choice || prompting.state.phase !== "prompting") {
      throw new Error("picker did not open");
    }
    const chosen = step(prompting.state, {
      type: "provider_chosen",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      spec: candidate.spec,
      choice,
      world: scene,
      draftIds: DRAFTS,
    });
    expect(connectOf(chosen.effects).selectNodeId).toBe("node-ocr");
  });

  it("opens beside the clicked port and ignores a click on a satisfied one", () => {
    const scene = world([mistral, reducto]);
    const picked = step(IDLE, {
      type: "pick_engine",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      consumer: consumer(),
      portName: "engine",
      world: scene,
      draftIds: DRAFTS,
    });
    expect(picked.state.phase).toBe("prompting");
    expect(openOf(picked.effects).servicePortName).toBe("engine");
    const ignored = step(IDLE, {
      type: "pick_engine",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      consumer: consumer(documentOcr, ["engine"]),
      portName: "engine",
      world: scene,
      draftIds: DRAFTS,
    });
    expect(ignored.state).toBe(IDLE);
  });

  it("ignores a choice that arrives after the prompt has closed", () => {
    const scene = world([mistral]);
    const result = step(IDLE, {
      type: "provider_chosen",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      spec: mistral,
      choice: {
        candidatePort: mistral.outputs[0]!,
        route: { kind: "exact", conversionPath: [] },
        collectionMode: "direct",
        usesInstancePlug: false,
      },
      world: scene,
      draftIds: DRAFTS,
    });
    expect(result.state).toBe(IDLE);
    expect(result.effects).toEqual([]);
  });

  it("closes an open prompt when the gesture is aborted", () => {
    const scene = world([mistral, reducto]);
    const prompting = step(IDLE, {
      type: "pick_engine",
      graphId: "graph-1",
      canEdit: true,
      running: false,
      consumer: consumer(),
      portName: "engine",
      world: scene,
      draftIds: DRAFTS,
    }).state;
    const closed = step(prompting, { type: "prompt_closed" });
    expect(closed.state).toEqual({ phase: "idle" });
    expect(closed.effects).toEqual([{ type: "close_prompt" }]);
    expect(step(IDLE, { type: "prompt_closed" }).state).toBe(IDLE);
  });
});
