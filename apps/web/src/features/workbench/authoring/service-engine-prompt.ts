/**
 * Post-placement engine prompt.
 *
 * A local placement gesture arms `awaiting_placement`. The host confirms the
 * node landed in this graph, then this reducer either connects the only
 * unambiguous provider or opens the picker. Collaboration, undo, load, and
 * MCP edits never dispatch the gesture, so they never arm it.
 *
 * No React, no DOM, no fetch. The host performs every effect.
 */
import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

import type { ExecEffect } from "@/lib/state/effect-reducer";

import { connectionRouteSelection } from "./connection-routes";
import type { GraphCommand } from "./graph-document";
import { addEdgeCommand, addNodeCommand } from "./graph-document-adapter";
import {
  catalogNodeKey,
  upstreamCandidatesFromInput,
  type ContextualCandidate,
  type ContextualRouteChoice,
} from "./node-catalog";
import {
  serviceProviderFlowPosition,
  serviceProviderPortAlignY,
  serviceProviderPositionLeftOf,
  type NodeTopLeft,
} from "./node-layout";
import { nodeSecretInputs } from "./node-secrets";
import { pendingWorkspaceKeyNotice } from "./pending-shared-binding";
import { serviceContractKey } from "./service-contract-key";
import {
  createWorkflowNodeData,
  portMetaForPort,
  type PortMeta,
} from "./types";

export type ServiceEngineReadiness =
  | "Ready (local)"
  | "Workspace key ready"
  | "Personal key available"
  | "Needs API key";

export interface ServiceEngineCandidateRow {
  readonly pills: readonly string[];
  readonly readiness: ServiceEngineReadiness;
}

export interface ServiceEngineConsumer {
  readonly id: string;
  readonly position: NodeTopLeft;
  readonly spec: NodeSpec;
  readonly satisfiedInputs: readonly string[];
}

export interface ServiceEngineCredential {
  readonly id: string;
  readonly label: string;
  readonly providerKind: string;
  readonly scope: "personal" | "shared";
}

export interface ServiceEngineDeploymentDefault {
  readonly operatorId: string;
  readonly secretName: string;
}

export interface ServiceEngineVault {
  readonly canEditProject: boolean;
  readonly credentials: readonly ServiceEngineCredential[];
  readonly deploymentDefaults: readonly ServiceEngineDeploymentDefault[];
}

export interface ServiceEngineWorld {
  readonly registry: NodeRegistry;
  readonly catalogNodes: readonly NodeSpec[];
  readonly vault: ServiceEngineVault;
}

export interface ServiceEngineDraftIds {
  readonly nodeId: string;
  readonly edgeId: string;
}

export type ServiceEnginePromptState =
  | { readonly phase: "idle" }
  | {
      readonly phase: "awaiting_placement";
      readonly graphId: string;
      readonly consumerNodeId: string;
      readonly servicePortName: string;
      readonly consumerPosition: NodeTopLeft;
    }
  | {
      readonly phase: "prompting";
      readonly graphId: string;
      readonly consumerNodeId: string;
      readonly servicePortName: string;
      readonly consumerPosition: NodeTopLeft;
      readonly consumerPortIndex: number;
    };

export type ServiceEnginePromptAction =
  | {
      readonly type: "local_placement";
      readonly origin: "node_selector" | "continue_from_port";
      readonly graphId: string;
      readonly canEdit: boolean;
      readonly running: boolean;
      readonly consumer: ServiceEngineConsumer;
    }
  | {
      readonly type: "placement_committed";
      readonly graphId: string;
      readonly canEdit: boolean;
      readonly running: boolean;
      readonly consumer: ServiceEngineConsumer | null;
      readonly world: ServiceEngineWorld | null;
      readonly draftIds: ServiceEngineDraftIds;
    }
  | {
      readonly type: "pick_engine";
      readonly graphId: string;
      readonly canEdit: boolean;
      readonly running: boolean;
      readonly consumer: ServiceEngineConsumer;
      readonly portName: string;
      readonly world: ServiceEngineWorld | null;
      readonly draftIds: ServiceEngineDraftIds;
      /** Skip the single-provider auto-wire and open the picker. */
      readonly openPicker: boolean;
    }
  | { readonly type: "abort" }
  | { readonly type: "prompt_closed" }
  | {
      readonly type: "gates";
      readonly graphId: string;
      readonly canEdit: boolean;
      readonly running: boolean;
    }
  | {
      readonly type: "provider_chosen";
      readonly graphId: string;
      readonly canEdit: boolean;
      readonly running: boolean;
      readonly spec: NodeSpec;
      readonly choice: ContextualRouteChoice;
      readonly world: ServiceEngineWorld;
      readonly draftIds: ServiceEngineDraftIds;
    };

export interface ServiceEngineSharedBinding {
  readonly secretName: string;
  readonly credentialId: string;
  readonly label: string;
}

export type ServiceEnginePromptEffect =
  | {
      readonly type: "open_prompt";
      readonly graphId: string;
      readonly consumerNodeId: string;
      readonly servicePortName: string;
      readonly portTitle: string;
      readonly flowPosition: NodeTopLeft;
      readonly providerPosition: NodeTopLeft;
      readonly candidates: readonly ContextualCandidate[];
      readonly rows: Readonly<Record<string, ServiceEngineCandidateRow>>;
    }
  | { readonly type: "close_prompt" }
  | {
      readonly type: "connect_provider";
      readonly commands: readonly GraphCommand[];
      readonly selectNodeId: string;
      readonly toast: string;
      readonly undoNodeId: string;
      readonly consumerNodeId: string;
      readonly providerTitle: string;
      readonly graphId: string;
      readonly bindings: readonly ServiceEngineSharedBinding[];
    };

const IDLE: ServiceEnginePromptState = { phase: "idle" };

export function initialServiceEnginePromptState(): ServiceEnginePromptState {
  return IDLE;
}

function gatesOpen(
  graphId: string,
  canEdit: boolean,
  running: boolean,
): boolean {
  return graphId.length > 0 && canEdit && !running;
}

function isInputPort(
  port: Port,
): port is Port & { readonly direction: "input" } {
  return port.direction === "input";
}

function isRequiredServiceInput(
  port: Port,
): port is Port & { readonly direction: "input"; readonly kind: "service" } {
  return (
    isInputPort(port) && port.kind === "service" && port.required !== false
  );
}

function firstUnsatisfiedServiceInput(
  consumer: ServiceEngineConsumer,
): (Port & { readonly direction: "input"; readonly kind: "service" }) | null {
  const satisfied = new Set(consumer.satisfiedInputs);
  for (const port of consumer.spec.inputs) {
    if (!isRequiredServiceInput(port) || satisfied.has(port.name)) continue;
    return port;
  }
  return null;
}

function unsatisfiedServiceInput(
  consumer: ServiceEngineConsumer,
  portName: string,
): (Port & { readonly direction: "input"; readonly kind: "service" }) | null {
  const port = consumer.spec.inputs.find(
    (candidate) => candidate.name === portName,
  );
  if (!port || !isRequiredServiceInput(port)) return null;
  if (consumer.satisfiedInputs.includes(port.name)) return null;
  return port;
}

function idleFrom(
  state: ServiceEnginePromptState,
  exec: ExecEffect<ServiceEnginePromptEffect>,
): ServiceEnginePromptState {
  if (state.phase === "prompting") exec({ type: "close_prompt" });
  return state.phase === "idle" ? state : IDLE;
}

interface SecretPlan {
  readonly auto: boolean;
  readonly bindings: readonly ServiceEngineSharedBinding[];
  readonly needsKey: boolean;
}

function credentialsFor(
  providerKind: string | undefined,
  vault: ServiceEngineVault,
  scope: ServiceEngineCredential["scope"],
): readonly ServiceEngineCredential[] {
  if (!providerKind) return [];
  return vault.credentials.filter(
    (credential) =>
      credential.scope === scope && credential.providerKind === providerKind,
  );
}

function hasDeploymentDefault(
  spec: NodeSpec,
  secretName: string,
  vault: ServiceEngineVault,
): boolean {
  return vault.deploymentDefaults.some(
    (entry) =>
      entry.operatorId === spec.operator_id && entry.secretName === secretName,
  );
}

/**
 * A provider is auto-bindable when it needs no key, or every key is already a
 * deployment default or exactly one shared credential this user can bind.
 * Two shared keys, a personal key, or a missing key all need a person to choose.
 */
function secretPlan(spec: NodeSpec, vault: ServiceEngineVault): SecretPlan {
  const secrets = nodeSecretInputs(spec);
  if (secrets.length === 0) {
    return { auto: true, bindings: [], needsKey: false };
  }
  const bindings: ServiceEngineSharedBinding[] = [];
  let auto = true;
  let needsKey = false;
  for (const secret of secrets) {
    if (hasDeploymentDefault(spec, secret.name, vault)) continue;
    const shared = credentialsFor(secret.providerKind, vault, "shared");
    const only = shared.length === 1 ? shared[0] : undefined;
    if (only && vault.canEditProject) {
      bindings.push({
        secretName: secret.name,
        credentialId: only.id,
        label: only.label,
      });
      continue;
    }
    auto = false;
    needsKey = true;
  }
  return { auto, bindings, needsKey };
}

/**
 * A deployment default is a server key, so the node can run without a vault
 * pick. That reads the same as a workspace key. Two shared keys still read as
 * ready: the user picks which one, but nothing is missing.
 */
export function credentialReadiness(
  spec: NodeSpec,
  vault: ServiceEngineVault,
): ServiceEngineReadiness {
  const secrets = nodeSecretInputs(spec);
  if (secrets.length === 0) return "Ready (local)";
  let personalOnly = false;
  for (const secret of secrets) {
    if (hasDeploymentDefault(spec, secret.name, vault)) continue;
    const shared = credentialsFor(secret.providerKind, vault, "shared");
    const personal = credentialsFor(secret.providerKind, vault, "personal");
    if (shared.length === 0 && personal.length === 0) return "Needs API key";
    if (shared.length === 0) personalOnly = true;
  }
  return personalOnly ? "Personal key available" : "Workspace key ready";
}

function formatFeature(feature: string): string {
  const words = feature.replaceAll("_", " ");
  if (words.length === 0) return feature;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function capabilityPills(
  provider: NodeSpec,
  consumer: NodeSpec,
  input: Port,
): readonly string[] {
  const accepted = new Set(
    (input.service_contracts ?? []).map((contract) =>
      serviceContractKey(contract),
    ),
  );
  const titles = new Map<string, string>();
  for (const output of consumer.outputs) {
    const requirement = output.requires_service_feature;
    if (!requirement || requirement.input_port !== input.name) continue;
    const title = output.title?.trim();
    if (title) titles.set(requirement.feature, title);
  }
  const pills: string[] = [];
  const seen = new Set<string>();
  for (const output of provider.outputs) {
    if (output.kind !== "service") continue;
    for (const entry of output.service_features ?? []) {
      if (!accepted.has(serviceContractKey(entry.contract))) continue;
      for (const feature of entry.features) {
        if (seen.has(feature)) continue;
        seen.add(feature);
        pills.push(titles.get(feature) ?? formatFeature(feature));
      }
    }
  }
  return pills;
}

function providerNeedsConfiguration(spec: NodeSpec): boolean {
  const required = spec.config_schema.required;
  const properties = spec.config_schema.properties;
  if (!Array.isArray(required)) return false;
  if (
    typeof properties !== "object" ||
    properties === null ||
    Array.isArray(properties)
  ) {
    return required.some((name) => typeof name === "string");
  }
  for (const name of required) {
    if (typeof name !== "string") continue;
    const property = Object.getOwnPropertyDescriptor(properties, name)?.value;
    if (
      typeof property !== "object" ||
      property === null ||
      Array.isArray(property)
    ) {
      return true;
    }
    if (!Object.prototype.hasOwnProperty.call(property, "default")) return true;
  }
  return false;
}

function connectToast(
  title: string,
  bindings: readonly ServiceEngineSharedBinding[],
): string {
  if (bindings.length === 0) return `Connected ${title}`;
  // The key is not bound yet. The host confirms the label after the write.
  return pendingWorkspaceKeyNotice(title);
}

function portMetaOrNull(port: Port): PortMeta | null {
  try {
    return portMetaForPort(port);
  } catch {
    return null;
  }
}

/** Compatible catalog nodes for one service input. Hidden nodes stay out. */
export function visibleEngineCandidates(input: {
  readonly port: Port;
  readonly registry: NodeRegistry;
  readonly catalogNodes: readonly NodeSpec[];
}): readonly ContextualCandidate[] {
  if (!isRequiredServiceInput(input.port)) return [];
  const targetMeta = portMetaOrNull(input.port);
  if (!targetMeta) return [];
  return upstreamCandidatesFromInput({
    targetPort: input.port,
    targetMeta,
    registry: input.registry,
    nodes: input.catalogNodes,
  });
}

interface ConnectInput {
  readonly graphId: string;
  readonly consumerId: string;
  readonly portName: string;
  readonly providerPosition: NodeTopLeft;
  readonly spec: NodeSpec;
  readonly choice: ContextualRouteChoice;
  readonly draftIds: ServiceEngineDraftIds;
  readonly plan: SecretPlan;
  readonly selectConsumer: boolean;
}

function connectEffect(
  input: ConnectInput,
): Extract<ServiceEnginePromptEffect, { type: "connect_provider" }> {
  const data = createWorkflowNodeData(input.spec);
  const binding = input.choice.route.artifactTypeBinding;
  if (binding?.endpoint === "source") {
    data.artifactTypeBindings = {
      ...data.artifactTypeBindings,
      [binding.variable]: binding.artifactType,
    };
  }
  const selection = connectionRouteSelection(input.choice.route);
  const nodeCommand = addNodeCommand(
    input.draftIds.nodeId,
    data,
    input.providerPosition,
  );
  const edgeCommand = addEdgeCommand(
    {
      source: input.draftIds.nodeId,
      sourcePort: input.choice.candidatePort.name,
      target: input.consumerId,
      targetPort: input.portName,
      targetPlug: null,
    },
    {
      enabled: true,
      collectionMode: input.choice.collectionMode,
      projection: selection.projection
        ? { path: [...selection.projection.path] }
        : undefined,
      conversionPath: selection.conversionPath.map((conversion) => ({
        id: conversion.id,
        version: conversion.version,
      })),
    },
    input.draftIds.edgeId,
  );
  const needsProvider =
    !input.selectConsumer &&
    (input.plan.needsKey || providerNeedsConfiguration(input.spec));
  return {
    type: "connect_provider",
    commands: [nodeCommand, edgeCommand],
    selectNodeId: needsProvider ? input.draftIds.nodeId : input.consumerId,
    toast: connectToast(input.spec.title, input.plan.bindings),
    undoNodeId: input.draftIds.nodeId,
    consumerNodeId: input.consumerId,
    providerTitle: input.spec.title,
    graphId: input.graphId,
    bindings: input.plan.bindings,
  };
}

/** Fixed inputs skip instance plugs, matching the operator card's port rows. */
function fixedInputIndex(spec: NodeSpec, portName: string): number {
  let index = 0;
  for (const port of spec.inputs) {
    if (port.instance_plugs === true) continue;
    if (port.name === portName) return index;
    index += 1;
  }
  return 0;
}

function outputPortIndex(spec: NodeSpec, portName: string): number {
  const index = spec.outputs.findIndex((port) => port.name === portName);
  return index < 0 ? 0 : index;
}

function providerTopLeft(
  consumer: ServiceEngineConsumer,
  consumerPortName: string,
  provider: NodeSpec,
  providerPortName: string,
): NodeTopLeft {
  return serviceProviderPositionLeftOf(
    consumer.position,
    serviceProviderPortAlignY(
      fixedInputIndex(consumer.spec, consumerPortName),
      outputPortIndex(provider, providerPortName),
    ),
  );
}

interface DecideInput {
  readonly graphId: string;
  readonly consumer: ServiceEngineConsumer;
  readonly port: Port & {
    readonly direction: "input";
    readonly kind: "service";
  };
  readonly world: ServiceEngineWorld;
  readonly draftIds: ServiceEngineDraftIds;
  /** The Pick engine pill sets this so one auto-bindable provider still opens. */
  readonly skipAuto: boolean;
}

interface DecideOutcome {
  readonly state: ServiceEnginePromptState;
  readonly effect: ServiceEnginePromptEffect | null;
}

function candidateRows(
  candidates: readonly ContextualCandidate[],
  port: Port,
  consumer: NodeSpec,
  vault: ServiceEngineVault,
): Readonly<Record<string, ServiceEngineCandidateRow>> {
  const rows: Record<string, ServiceEngineCandidateRow> = {};
  for (const candidate of candidates) {
    rows[catalogNodeKey(candidate.spec)] = {
      pills: capabilityPills(candidate.spec, consumer, port),
      readiness: credentialReadiness(candidate.spec, vault),
    };
  }
  return rows;
}

function decide(input: DecideInput): DecideOutcome {
  const candidates = visibleEngineCandidates({
    port: input.port,
    registry: input.world.registry,
    catalogNodes: input.world.catalogNodes,
  });
  if (candidates.length === 0) return { state: IDLE, effect: null };

  const sole = candidates.length === 1 ? candidates[0] : undefined;
  const onlyChoice = sole?.choices.length === 1 ? sole.choices[0] : undefined;
  if (!input.skipAuto && sole && onlyChoice) {
    const plan = secretPlan(sole.spec, input.world.vault);
    if (plan.auto) {
      return {
        state: IDLE,
        effect: connectEffect({
          graphId: input.graphId,
          consumerId: input.consumer.id,
          portName: input.port.name,
          providerPosition: providerTopLeft(
            input.consumer,
            input.port.name,
            sole.spec,
            onlyChoice.candidatePort.name,
          ),
          spec: sole.spec,
          choice: onlyChoice,
          draftIds: input.draftIds,
          plan,
          selectConsumer: true,
        }),
      };
    }
  }

  // The ghost has no chosen provider yet, so its output row is the first one.
  const ghostPosition = serviceProviderPositionLeftOf(
    input.consumer.position,
    serviceProviderPortAlignY(
      fixedInputIndex(input.consumer.spec, input.port.name),
      0,
    ),
  );
  return {
    state: {
      phase: "prompting",
      graphId: input.graphId,
      consumerNodeId: input.consumer.id,
      servicePortName: input.port.name,
      consumerPosition: input.consumer.position,
      consumerPortIndex: fixedInputIndex(input.consumer.spec, input.port.name),
    },
    effect: {
      type: "open_prompt",
      graphId: input.graphId,
      consumerNodeId: input.consumer.id,
      servicePortName: input.port.name,
      portTitle: input.port.title?.trim() || input.port.name,
      flowPosition: serviceProviderFlowPosition(ghostPosition),
      providerPosition: ghostPosition,
      candidates,
      rows: candidateRows(
        candidates,
        input.port,
        input.consumer.spec,
        input.world.vault,
      ),
    },
  };
}

function finish(
  state: ServiceEnginePromptState,
  outcome: DecideOutcome,
  exec: ExecEffect<ServiceEnginePromptEffect>,
): ServiceEnginePromptState {
  if (state.phase === "prompting" && outcome.state.phase !== "prompting") {
    exec({ type: "close_prompt" });
  }
  if (outcome.effect) exec(outcome.effect);
  return outcome.state.phase === "idle" ? IDLE : outcome.state;
}

export function serviceEnginePromptReducer(
  state: ServiceEnginePromptState,
  action: ServiceEnginePromptAction,
  exec: ExecEffect<ServiceEnginePromptEffect>,
): ServiceEnginePromptState {
  switch (action.type) {
    case "local_placement": {
      if (!gatesOpen(action.graphId, action.canEdit, action.running)) {
        return idleFrom(state, exec);
      }
      const port = firstUnsatisfiedServiceInput(action.consumer);
      if (!port) return idleFrom(state, exec);
      if (state.phase === "prompting") exec({ type: "close_prompt" });
      return {
        phase: "awaiting_placement",
        graphId: action.graphId,
        consumerNodeId: action.consumer.id,
        servicePortName: port.name,
        consumerPosition: action.consumer.position,
      };
    }
    case "placement_committed": {
      if (state.phase !== "awaiting_placement") return state;
      if (
        !gatesOpen(action.graphId, action.canEdit, action.running) ||
        action.graphId !== state.graphId ||
        !action.consumer ||
        action.consumer.id !== state.consumerNodeId
      ) {
        return idleFrom(state, exec);
      }
      if (!action.world) return state;
      const port = unsatisfiedServiceInput(
        action.consumer,
        state.servicePortName,
      );
      if (!port) return idleFrom(state, exec);
      return finish(
        state,
        decide({
          graphId: action.graphId,
          consumer: action.consumer,
          port,
          world: action.world,
          draftIds: action.draftIds,
          skipAuto: false,
        }),
        exec,
      );
    }
    case "pick_engine": {
      if (
        !gatesOpen(action.graphId, action.canEdit, action.running) ||
        !action.world
      ) {
        return idleFrom(state, exec);
      }
      const port = unsatisfiedServiceInput(action.consumer, action.portName);
      if (!port) return idleFrom(state, exec);
      return finish(
        state,
        decide({
          graphId: action.graphId,
          consumer: action.consumer,
          port,
          world: action.world,
          draftIds: action.draftIds,
          skipAuto: action.openPicker,
        }),
        exec,
      );
    }
    case "abort":
    case "prompt_closed":
      return idleFrom(state, exec);
    case "gates": {
      if (state.phase === "idle") return state;
      if (
        !gatesOpen(action.graphId, action.canEdit, action.running) ||
        action.graphId !== state.graphId
      ) {
        return idleFrom(state, exec);
      }
      return state;
    }
    case "provider_chosen": {
      if (state.phase !== "prompting") return state;
      if (
        !gatesOpen(action.graphId, action.canEdit, action.running) ||
        action.graphId !== state.graphId
      ) {
        return idleFrom(state, exec);
      }
      const plan = secretPlan(action.spec, action.world.vault);
      const providerPosition = serviceProviderPositionLeftOf(
        state.consumerPosition,
        serviceProviderPortAlignY(
          state.consumerPortIndex,
          outputPortIndex(action.spec, action.choice.candidatePort.name),
        ),
      );
      return finish(
        state,
        {
          state: IDLE,
          effect: connectEffect({
            graphId: action.graphId,
            consumerId: state.consumerNodeId,
            portName: state.servicePortName,
            providerPosition,
            spec: action.spec,
            choice: action.choice,
            draftIds: action.draftIds,
            plan,
            selectConsumer: false,
          }),
        },
        exec,
      );
    }
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}
