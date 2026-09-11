"use client";

import * as React from "react";
import { SWRConfig, type Cache, type State } from "swr";

import { ThresholdStatus } from "@/components/threshold-status";
import {
  deleteSession,
  getSession,
  oidcLoginUrl,
  safeReturnPath,
} from "@/lib/api/auth";
import { ApiError, onUnauthorized } from "@/lib/api/client";
import type { Session } from "@/lib/api/contract";
import { sandboxSession } from "./dev-session";

type AuthState =
  | { kind: "loading" }
  | { kind: "signed-out" }
  | { kind: "authenticated"; session: Session }
  | { kind: "expired" }
  | { kind: "unavailable" }
  | { kind: "signing-out" }
  | { kind: "logout-failed" };

interface AuthSessionContextValue {
  session: Session;
  logout: () => Promise<void>;
}

const AuthSessionContext = React.createContext<AuthSessionContextValue | null>(
  null,
);

export function sessionFailureKind(
  error: unknown,
): "signed-out" | "unavailable" {
  return error instanceof ApiError && error.status === 401
    ? "signed-out"
    : "unavailable";
}

function createProtectedSWRCache(): Cache<unknown> {
  return new Map<string, State<unknown>>();
}

function readReturnPath(): string {
  if (typeof window === "undefined") return "/graphs";
  return safeReturnPath(`${window.location.pathname}${window.location.search}`);
}

function openLogin(): void {
  if (typeof window === "undefined") return;
  window.location.assign(oidcLoginUrl(readReturnPath()));
}

function AuthFrame({
  state,
  onLogout,
  onRetry,
  cacheGeneration,
  children,
}: {
  state: AuthState;
  onLogout: () => Promise<void>;
  onRetry: () => void;
  cacheGeneration: number;
  children: React.ReactNode;
}) {
  if (state.kind === "loading") {
    return (
      <ThresholdStatus
        title="Checking session"
        detail="Opening your graphs…"
        loading
      />
    );
  }
  if (state.kind === "signed-out") {
    return (
      <ThresholdStatus
        title="Sign in"
        detail="Your graphs and Team locations are available after authentication."
        action={
          <button type="button" onClick={openLogin}>
            Continue with SSO
          </button>
        }
      />
    );
  }
  if (state.kind === "expired") {
    return (
      <ThresholdStatus
        title="Your session has expired"
        detail="Sign in again to return to the same surface."
        action={
          <button type="button" onClick={openLogin}>
            Sign in again
          </button>
        }
      />
    );
  }
  if (state.kind === "unavailable") {
    return (
      <ThresholdStatus
        title="Session service unavailable"
        detail="Could not confirm your session. Check the connection and try again."
        action={
          <button type="button" onClick={onRetry}>
            Try again
          </button>
        }
      />
    );
  }
  if (state.kind === "signing-out") {
    return (
      <ThresholdStatus
        title="Signing out"
        detail="Revoking this session…"
        loading
      />
    );
  }
  if (state.kind === "logout-failed") {
    return (
      <ThresholdStatus
        title="Sign out could not be completed"
        detail="The server could not revoke this session. Try again before leaving."
        action={
          <button type="button" onClick={onLogout}>
            Try sign out again
          </button>
        }
      />
    );
  }

  return (
    <SWRConfig
      key={`protected-cache-${cacheGeneration}-${state.session.id}-${state.session.user_id}`}
      value={{ provider: createProtectedSWRCache }}
    >
      <AuthSessionContext.Provider
        value={{ session: state.session, logout: onLogout }}
      >
        {children}
      </AuthSessionContext.Provider>
    </SWRConfig>
  );
}

export function useAuthSession(): AuthSessionContextValue {
  const context = React.useContext(AuthSessionContext);
  if (!context)
    throw new Error("useAuthSession must be used inside AuthSessionBoundary");
  return context;
}

export function AuthSessionBoundary({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = React.useState<AuthState>(() => {
    const devSession = sandboxSession();
    return devSession
      ? { kind: "authenticated", session: devSession }
      : { kind: "loading" };
  });
  const [cacheGeneration, setCacheGeneration] = React.useState(0);
  const logoutAttemptRef = React.useRef(0);
  const logoutInFlightRef = React.useRef(false);

  const expireSession = React.useCallback(() => {
    setState((current) =>
      current.kind === "authenticated" ? { kind: "expired" } : current,
    );
  }, []);

  React.useEffect(() => onUnauthorized(expireSession), [expireSession]);

  const loadSession = React.useCallback((signal: AbortSignal) => {
    void getSession(signal)
      .then((session) => {
        setCacheGeneration((current) => current + 1);
        setState({ kind: "authenticated", session });
      })
      .catch((error: unknown) => {
        if (signal.aborted) return;
        setState({ kind: sessionFailureKind(error) });
      });
  }, []);

  React.useEffect(() => {
    const controller = new AbortController();
    if (sandboxSession()) return () => controller.abort();
    loadSession(controller.signal);
    return () => controller.abort();
  }, [loadSession]);

  const logout = React.useCallback(async () => {
    if (logoutInFlightRef.current) return;
    logoutInFlightRef.current = true;
    const attempt = logoutAttemptRef.current + 1;
    logoutAttemptRef.current = attempt;
    setState({ kind: "signing-out" });
    try {
      await deleteSession();
      if (attempt !== logoutAttemptRef.current) return;
      setState({ kind: "signed-out" });
    } catch (error) {
      if (attempt !== logoutAttemptRef.current) return;
      if (error instanceof ApiError && error.status === 401) {
        setState({ kind: "signed-out" });
        return;
      }
      setState({ kind: "logout-failed" });
    } finally {
      if (attempt === logoutAttemptRef.current)
        logoutInFlightRef.current = false;
    }
  }, []);

  return (
    <AuthFrame
      state={state}
      onLogout={logout}
      cacheGeneration={cacheGeneration}
      onRetry={() => {
        setState({ kind: "loading" });
        loadSession(new AbortController().signal);
      }}
    >
      {state.kind === "authenticated" ? children : null}
    </AuthFrame>
  );
}
