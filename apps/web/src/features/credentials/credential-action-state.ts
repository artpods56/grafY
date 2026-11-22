export type CredentialActionState =
  | { kind: "idle" }
  | { kind: "pending"; id: string }
  | { kind: "complete"; message: string }
  | { kind: "failed"; message: string };

export type CredentialAction<Operation> =
  | { kind: "start"; id: string; operation: Operation }
  | { kind: "resolve"; message?: string }
  | { kind: "reject"; message: string };

export type CredentialActionEffect<Operation> = {
  kind: "execute";
  operation: Operation;
};

export function credentialActionReducer<Operation>(
  state: CredentialActionState,
  action: CredentialAction<Operation>,
  exec: (effect: CredentialActionEffect<Operation>) => void,
): CredentialActionState {
  if (action.kind === "start") {
    if (state.kind === "pending") return state;
    exec({ kind: "execute", operation: action.operation });
    return { kind: "pending", id: action.id };
  }
  if (state.kind !== "pending") return state;
  if (action.kind === "reject")
    return { kind: "failed", message: action.message };
  return action.message
    ? { kind: "complete", message: action.message }
    : { kind: "idle" };
}
