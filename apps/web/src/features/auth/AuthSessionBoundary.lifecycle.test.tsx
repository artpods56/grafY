// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import useSWR, { SWRConfig, type State } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const authMocks = vi.hoisted(() => ({
  getSession: vi.fn(),
  deleteSession: vi.fn(),
}));

vi.mock("@/lib/api/auth", () => ({
  getSession: authMocks.getSession,
  deleteSession: authMocks.deleteSession,
  oidcLoginUrl: () => "/api/v1/auth/oidc/login?return_path=%2Fworkspaces",
  safeReturnPath: (path: string) => path,
}));

import { ApiError, request } from "@/lib/api/client";
import { AuthSessionBoundary, useAuthSession } from "./AuthSessionBoundary";

const session = {
  id: "session-1",
  user_id: "user-1",
  email: "owner@example.test",
  display_name: "Ada Lovelace",
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-01-02T00:00:00Z",
  last_used_at: null,
  revoked_at: null,
  current: true,
};

let logoutControl: (() => Promise<void>) | undefined;

function ProtectedSurface({
  onLogoutReady,
}: {
  onLogoutReady: (logout: () => Promise<void>) => void;
}) {
  const { logout } = useAuthSession();
  React.useEffect(() => onLogoutReady(logout), [logout, onLogoutReady]);
  return (
    <div>
      <div data-protected="true">protected</div>
      <button type="button" onClick={() => void logout()}>
        Log out
      </button>
    </div>
  );
}

const captureLogout = (logout: () => Promise<void>) => {
  logoutControl = logout;
};

function ProtectedData() {
  const { data } = useSWR<string>("same-key");
  return <div data-protected-data>{data ?? "loading"}</div>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  authMocks.getSession.mockReset();
  authMocks.deleteSession.mockReset();
  logoutControl = undefined;
});

describe("AuthSessionBoundary lifecycle", () => {
  it("drops protected children while a delayed 401 body is still being consumed", async () => {
    authMocks.getSession.mockResolvedValue(session);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <AuthSessionBoundary>
          <ProtectedSurface onLogoutReady={captureLogout} />
        </AuthSessionBoundary>,
      ),
    );
    expect(container.querySelector("[data-protected]")).not.toBeNull();

    let bodyController: ReadableStreamDefaultController<Uint8Array> | undefined;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        bodyController = controller;
        controller.enqueue(new TextEncoder().encode("{"));
      },
      pull() {
        return new Promise<void>(() => undefined);
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(body, { status: 401 })),
    );

    let requestSettled = false;
    const unauthorizedRequest = request("GET", "/v1/protected");
    const observedRequest = unauthorizedRequest.then(
      () => {
        requestSettled = true;
      },
      () => {
        requestSettled = true;
      },
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.querySelector("[data-protected]")).toBeNull();
    expect(container.textContent).toContain("Your session has expired");
    expect(requestSettled).toBe(false);

    bodyController?.error(
      new Error("body intentionally left pending after boundary cleanup"),
    );
    await observedRequest;
    await expect(unauthorizedRequest).rejects.toMatchObject({ status: 401 });
    await act(async () => root.unmount());
  });

  it("shows a non-interactive signing-out state and ignores overlapping logout calls", async () => {
    authMocks.getSession.mockResolvedValue(session);
    let resolveDelete: (() => void) | undefined;
    authMocks.deleteSession.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveDelete = resolve;
        }),
    );
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <AuthSessionBoundary>
          <ProtectedSurface onLogoutReady={captureLogout} />
        </AuthSessionBoundary>,
      ),
    );

    const firstAttempt = logoutControl?.();
    logoutControl?.();
    await act(async () => Promise.resolve());
    expect(authMocks.deleteSession).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Signing out");
    expect(container.querySelector("button")).toBeNull();

    resolveDelete?.();
    await act(async () => firstAttempt);
    expect(container.textContent).toContain("Continue with SSO");
    await act(async () => root.unmount());
  });

  it("treats a 401 logout response as a successful signed-out outcome", async () => {
    authMocks.getSession.mockResolvedValue(session);
    authMocks.deleteSession.mockRejectedValue(new ApiError(401, "expired"));
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <AuthSessionBoundary>
          <ProtectedSurface onLogoutReady={captureLogout} />
        </AuthSessionBoundary>,
      ),
    );

    await act(async () => logoutControl?.());
    expect(container.textContent).toContain("Continue with SSO");
    expect(container.textContent).not.toContain("expired");
    await act(async () => root.unmount());
  });

  it("allows a retry after a lost logout response and accepts 401 on that retry", async () => {
    authMocks.getSession.mockResolvedValue(session);
    authMocks.deleteSession
      .mockRejectedValueOnce(new Error("lost response"))
      .mockRejectedValueOnce(new ApiError(401, "already revoked"));
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <AuthSessionBoundary>
          <ProtectedSurface onLogoutReady={captureLogout} />
        </AuthSessionBoundary>,
      ),
    );

    await act(async () => logoutControl?.());
    expect(container.textContent).toContain("Sign out could not be completed");
    await act(async () => {
      container
        .querySelector("button")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(authMocks.deleteSession).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Continue with SSO");
    await act(async () => root.unmount());
  });

  it("keeps a 403 logout failure retryable without exposing server detail", async () => {
    authMocks.getSession.mockResolvedValue(session);
    authMocks.deleteSession
      .mockRejectedValueOnce(new ApiError(403, "private server detail"))
      .mockResolvedValueOnce(undefined);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () =>
      root.render(
        <AuthSessionBoundary>
          <ProtectedSurface onLogoutReady={captureLogout} />
        </AuthSessionBoundary>,
      ),
    );

    await act(async () => logoutControl?.());
    expect(container.textContent).toContain("Sign out could not be completed");
    expect(container.textContent).not.toContain("private server detail");
    await act(async () => {
      container
        .querySelector("button")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(container.textContent).toContain("Continue with SSO");
    await act(async () => root.unmount());
  });

  it("does not expose a deferred result through the next rendered protected cache", async () => {
    authMocks.getSession
      .mockResolvedValueOnce(session)
      .mockResolvedValueOnce({ ...session, id: "session-2" });
    let resolveStale: ((value: string) => void) | undefined;
    const staleRequest = new Promise<string>((resolve) => {
      resolveStale = resolve;
    });
    const fetcher = vi
      .fn()
      .mockReturnValueOnce(staleRequest)
      .mockResolvedValueOnce("fresh response");
    const outerCache = new Map<string, State<unknown>>();
    const container = document.createElement("div");
    const root = createRoot(container);
    const renderBoundary = (key: string) => (
      <SWRConfig
        value={{
          provider: () => outerCache,
          fetcher,
          revalidateOnFocus: false,
        }}
      >
        <AuthSessionBoundary key={key}>
          <ProtectedData />
        </AuthSessionBoundary>
      </SWRConfig>
    );

    await act(async () => root.render(renderBoundary("first")));
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce());

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );
    const unauthorizedRequest = request("GET", "/v1/protected").catch(
      (error: unknown) => error,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.querySelector("[data-protected-data]")).toBeNull();
    await expect(unauthorizedRequest).resolves.toMatchObject({ status: 401 });

    resolveStale?.("stale response");
    await act(async () => staleRequest);

    await act(async () => root.render(renderBoundary("second")));
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(container.textContent).toContain("fresh response");
    expect(container.textContent).not.toContain("stale response");
    expect(outerCache.get("same-key")).toBeUndefined();
    await act(async () => root.unmount());
  });
});
