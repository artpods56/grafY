"use client";

import { credentialVerificationFailure } from "@/lib/api/credentials";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import {
  credentialActionReducer,
  type CredentialAction,
  type CredentialActionEffect,
  type CredentialActionState,
} from "./credential-action-state";

export function useCredentialAction<Operation>(
  run: (operation: Operation) => Promise<string | void>,
) {
  return useEffectReducer<
    CredentialActionState,
    CredentialAction<Operation>,
    CredentialActionEffect<Operation>
  >(
    credentialActionReducer,
    { kind: "idle" },
    (effect, dispatch) => {
      void run(effect.operation).then(
        (message) =>
          dispatch({ kind: "resolve", message: message ?? undefined }),
        (error: unknown) =>
          dispatch({
            kind: "reject",
            message: credentialVerificationFailure(error).message,
          }),
      );
    },
    { flush: "sync" },
  );
}
