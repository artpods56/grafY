import type { NodeSecretStatus, NodeSpec, SavedGraphNode } from "@/lib/api";

export interface WorkflowNodeSecretInput {
  name: string;
  title: string;
  description?: string;
  configDependencies: readonly string[];
}

export type WorkflowNodeSecretState =
  | "unknown"
  | "loading"
  | "unconfigured"
  | "configured"
  | "stale"
  | "applying"
  | "removing"
  | "error";

export interface WorkflowNodeSecretStatus {
  state: WorkflowNodeSecretState;
  message?: string;
}

export type WorkflowNodeSecretStatuses = Readonly<
  Record<string, WorkflowNodeSecretStatus>
>;

export type RemoteNodeSecretStatus = NodeSecretStatus;

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** Reads declarative write-only inputs without trusting plugin-owned metadata. */
export function nodeSecretInputs(spec: NodeSpec): WorkflowNodeSecretInput[] {
  const rawInputs = spec.secret_inputs;
  if (!Array.isArray(rawInputs)) return [];

  const seen = new Set<string>();
  return rawInputs.flatMap((rawInput) => {
    const input = record(rawInput);
    if (
      !input ||
      typeof input.name !== "string" ||
      input.name.length === 0 ||
      seen.has(input.name) ||
      !Array.isArray(input.config_dependencies) ||
      !input.config_dependencies.every(
        (dependency) => typeof dependency === "string" && dependency.length > 0,
      )
    ) {
      return [];
    }
    if (
      input.title !== undefined &&
      input.title !== null &&
      typeof input.title !== "string"
    ) {
      return [];
    }
    if (
      input.description !== undefined &&
      input.description !== null &&
      typeof input.description !== "string"
    ) {
      return [];
    }

    seen.add(input.name);
    return [
      {
        name: input.name,
        title:
          typeof input.title === "string" && input.title.length > 0
            ? input.title
            : input.name.replaceAll("_", " "),
        description:
          typeof input.description === "string" ? input.description : undefined,
        configDependencies: input.config_dependencies,
      },
    ];
  });
}

export function nodeSecretDependencyRevision(
  input: WorkflowNodeSecretInput,
  config: Readonly<Record<string, unknown>>,
): string {
  return JSON.stringify(
    input.configDependencies.map((dependency) => [
      dependency,
      config[dependency] ?? null,
    ]),
  );
}

type NodeSecretBindingSnapshot = Pick<
  SavedGraphNode,
  "id" | "operator_id" | "operator_version" | "config"
>;

/** Whether one secret input still targets the exact binding saved by the graph. */
export function nodeSecretBindingReady(
  input: WorkflowNodeSecretInput,
  currentNode: NodeSecretBindingSnapshot,
  savedNode: NodeSecretBindingSnapshot | undefined,
): boolean {
  if (
    !savedNode ||
    currentNode.id !== savedNode.id ||
    currentNode.operator_id !== savedNode.operator_id ||
    currentNode.operator_version !== savedNode.operator_version
  ) {
    return false;
  }

  return (
    nodeSecretDependencyRevision(input, currentNode.config ?? {}) ===
    nodeSecretDependencyRevision(input, savedNode.config ?? {})
  );
}

export function reconciledNodeSecretStatuses(
  spec: NodeSpec,
  nodeId: string,
  remote: readonly RemoteNodeSecretStatus[],
): WorkflowNodeSecretStatuses {
  const remoteByName = new Map(
    remote
      .filter((status) => status.node_id === nodeId)
      .map((status) => [status.name, status]),
  );
  return Object.fromEntries(
    nodeSecretInputs(spec).map((input) => [
      input.name,
      {
        state: remoteByName.get(input.name)?.configured
          ? "configured"
          : "unconfigured",
      } satisfies WorkflowNodeSecretStatus,
    ]),
  );
}
