/**
 * When a shared workspace key may be written onto a provider the engine
 * prompt just placed.
 *
 * The graph batch lands first. The credential write has to wait until that
 * provider is on the saved head, and it has to be dropped if the person
 * undoes the provider or leaves the graph. Nothing here talks to the network.
 */

export interface PendingSharedBinding {
  readonly nodeId: string;
  readonly secretName: string;
  readonly credentialId: string;
  readonly providerTitle: string;
  readonly credentialLabel: string;
  readonly graphId: string;
}

export type PendingBindingDecision = "wait" | "drop" | "write";

export function decidePendingBinding(input: {
  readonly binding: PendingSharedBinding;
  readonly graphId: string | null;
  readonly canvasNodeIds: ReadonlySet<string>;
  readonly savedNodeIds: ReadonlySet<string>;
}): PendingBindingDecision {
  if (input.binding.graphId !== input.graphId) return "drop";
  if (!input.canvasNodeIds.has(input.binding.nodeId)) return "drop";
  if (!input.savedNodeIds.has(input.binding.nodeId)) return "wait";
  return "write";
}

export function partitionPendingBindings<
  Binding extends PendingSharedBinding,
>(input: {
  readonly pending: readonly Binding[];
  readonly graphId: string | null;
  readonly canvasNodeIds: ReadonlySet<string>;
  readonly savedNodeIds: ReadonlySet<string>;
}): {
  readonly waiting: readonly Binding[];
  readonly ready: readonly Binding[];
} {
  const waiting: Binding[] = [];
  const ready: Binding[] = [];
  for (const binding of input.pending) {
    const decision = decidePendingBinding({
      binding,
      graphId: input.graphId,
      canvasNodeIds: input.canvasNodeIds,
      savedNodeIds: input.savedNodeIds,
    });
    if (decision === "wait") waiting.push(binding);
    if (decision === "write") ready.push(binding);
  }
  return { waiting, ready };
}

/** A message safe to show. Never empty, so a failure cannot be swallowed. */
export function bindingFailureMessage(error: unknown): string {
  if (error instanceof Error) {
    const message = error.message.trim();
    if (message.length > 0) return message;
  }
  if (typeof error === "string") {
    const message = error.trim();
    if (message.length > 0) return message;
  }
  return "Could not bind the workspace key.";
}

export function pendingWorkspaceKeyNotice(title: string): string {
  return `Connected ${title} · binding workspace key…`;
}

export function boundWorkspaceKeyNotice(
  title: string,
  labels: readonly string[],
): string {
  const first = labels[0];
  if (!first) return `Connected ${title}`;
  if (labels.length === 1) {
    return `Connected ${title} using workspace key '${first}'`;
  }
  const quoted = labels.map((label) => `'${label}'`).join(", ");
  return `Connected ${title} using workspace keys ${quoted}`;
}

export function workspaceKeyBindFailedNotice(
  title: string,
  message: string,
): string {
  return `Connected ${title}. The workspace key was not bound: ${message}`;
}
