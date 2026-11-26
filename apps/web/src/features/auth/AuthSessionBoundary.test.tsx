// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

import { ApiError } from "@/lib/api/client";
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

function LogoutButton() {
  const { logout } = useAuthSession();
  return (
    <button type="button" onClick={() => void logout()}>
      Log out
    </button>
  );
}

async function renderAuthenticated(
  child: React.ReactNode = <div data-protected="true">protected</div>,
) {
  const container = document.createElement("div");
  const root = createRoot(container);
  await act(async () => {
    root.render(<AuthSessionBoundary>{child}</AuthSessionBoundary>);
  });
  return { container, root };
}

async function flush(work: () => void): Promise<void> {
  await act(async () => {
    work();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

beforeEach(() => {
  authMocks.getSession.mockReset();
  authMocks.deleteSession.mockReset();
  authMocks.getSession.mockResolvedValue(session);
  setVisibility("visible");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("AuthSessionBoundary revalidation", () => {
  it("expires the session when a focused tab's revalidation returns 401", async () => {
    authMocks.getSession
      .mockResolvedValueOnce(session)
      .mockRejectedValueOnce(new ApiError(401, "unauthorized"));
    const { container, root } = await renderAuthenticated();
    expect(container.querySelector("[data-protected]")).not.toBeNull();

    await flush(() => window.dispatchEvent(new Event("focus")));

    expect(authMocks.getSession).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-protected]")).toBeNull();
    expect(container.textContent).toContain("Your session has expired");
    await act(async () => root.unmount());
  });

  it("expires the session when the tab becomes visible and revalidation returns 401", async () => {
    authMocks.getSession
      .mockResolvedValueOnce(session)
      .mockRejectedValueOnce(new ApiError(401, "unauthorized"));
    const { container, root } = await renderAuthenticated();

    setVisibility("hidden");
    await flush(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(authMocks.getSession).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-protected]")).not.toBeNull();

    setVisibility("visible");
    await flush(() => document.dispatchEvent(new Event("visibilitychange")));

    expect(authMocks.getSession).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("Your session has expired");
    await act(async () => root.unmount());
  });

  it("stays authenticated when revalidation fails with 500", async () => {
    authMocks.getSession.mockReset();
    authMocks.getSession
      .mockResolvedValueOnce(session)
      .mockRejectedValue(new ApiError(500, "unavailable"));
    const { container, root } = await renderAuthenticated();

    await flush(() => window.dispatchEvent(new Event("focus")));

    expect(authMocks.getSession).toHaveBeenCalledTimes(2);
    expect(container.querySelector("[data-protected]")).not.toBeNull();
    expect(container.textContent).not.toContain("Your session has expired");
    expect(container.textContent).not.toContain("unavailable");
    await act(async () => root.unmount());
  });

  it("stays authenticated when revalidation fails with a network error", async () => {
    authMocks.getSession.mockReset();
    authMocks.getSession
      .mockResolvedValueOnce(session)
      .mockRejectedValue(new TypeError("network unavailable"));
    const { container, root } = await renderAuthenticated();

    await flush(() => window.dispatchEvent(new Event("focus")));
    await flush(() => window.dispatchEvent(new Event("focus")));

    expect(authMocks.getSession).toHaveBeenCalledTimes(3);
    expect(container.querySelector("[data-protected]")).not.toBeNull();
    expect(container.textContent).not.toContain("Your session has expired");
    await act(async () => root.unmount());
  });

  it("does not start another probe while one is in flight", async () => {
    let release: ((value: typeof session) => void) | undefined;
    let calls = 0;
    authMocks.getSession.mockImplementation(() => {
      calls += 1;
      if (calls === 1) return Promise.resolve(session);
      return new Promise<typeof session>((resolve) => {
        release = resolve;
      });
    });
    const { root } = await renderAuthenticated();

    await flush(() => window.dispatchEvent(new Event("focus")));
    await flush(() => document.dispatchEvent(new Event("visibilitychange")));

    expect(calls).toBe(2);
    release?.(session);
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => root.unmount());
  });

  it("skips probes for 30 seconds after a successful revalidation", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-06-01T00:00:00.000Z"));
    const { container, root } = await renderAuthenticated();
    expect(authMocks.getSession).toHaveBeenCalledOnce();

    await flush(() => window.dispatchEvent(new Event("focus")));
    expect(authMocks.getSession).toHaveBeenCalledTimes(2);

    await flush(() => window.dispatchEvent(new Event("focus")));
    expect(authMocks.getSession).toHaveBeenCalledTimes(2);

    vi.setSystemTime(new Date("2026-06-01T00:00:29.000Z"));
    await flush(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(authMocks.getSession).toHaveBeenCalledTimes(2);

    vi.setSystemTime(new Date("2026-06-01T00:00:30.000Z"));
    await flush(() => window.dispatchEvent(new Event("focus")));
    expect(authMocks.getSession).toHaveBeenCalledTimes(3);
    expect(container.querySelector("[data-protected]")).not.toBeNull();
    await act(async () => root.unmount());
  });

  it("aborts an in-flight revalidation when the boundary unmounts", async () => {
    const signals: Array<AbortSignal | undefined> = [];
    authMocks.getSession.mockImplementation((signal?: AbortSignal) => {
      signals.push(signal);
      if (signals.length === 1) return Promise.resolve(session);
      return new Promise<typeof session>((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new ApiError(401, "unauthorized"));
        });
      });
    });
    const { container, root } = await renderAuthenticated();

    await flush(() => window.dispatchEvent(new Event("focus")));
    expect(signals).toHaveLength(2);
    const probe = signals[1];
    expect(probe?.aborted).toBe(false);

    await act(async () => root.unmount());
    await act(async () => {
      await Promise.resolve();
    });

    expect(probe?.aborted).toBe(true);
    expect(container.textContent).not.toContain("Your session has expired");
    await flush(() => window.dispatchEvent(new Event("focus")));
    expect(signals).toHaveLength(2);
  });

  it("aborts an in-flight revalidation when the session leaves authenticated", async () => {
    const signals: Array<AbortSignal | undefined> = [];
    authMocks.getSession.mockImplementation((signal?: AbortSignal) => {
      signals.push(signal);
      if (signals.length === 1) return Promise.resolve(session);
      return new Promise<typeof session>((_resolve, reject) => {
        signal?.addEventListener("abort", () => {
          reject(new ApiError(401, "unauthorized"));
        });
      });
    });
    authMocks.deleteSession.mockImplementation(
      () => new Promise<void>(() => undefined),
    );
    const { container, root } = await renderAuthenticated(<LogoutButton />);

    await flush(() => window.dispatchEvent(new Event("focus")));
    const probe = signals[1];
    await flush(() => {
      container
        .querySelector("button")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(probe?.aborted).toBe(true);
    expect(container.textContent).toContain("Signing out");
    expect(container.textContent).not.toContain("Your session has expired");
    await act(async () => root.unmount());
  });

  it("does not revalidate a sandbox session", async () => {
    vi.stubEnv("NEXT_PUBLIC_GRAFY_DEV_SESSION", "1");
    authMocks.getSession.mockRejectedValue(new ApiError(401, "unauthorized"));
    const { container, root } = await renderAuthenticated();

    await flush(() => window.dispatchEvent(new Event("focus")));
    await flush(() => document.dispatchEvent(new Event("visibilitychange")));

    expect(authMocks.getSession).not.toHaveBeenCalled();
    expect(container.querySelector("[data-protected]")).not.toBeNull();
    await act(async () => root.unmount());
  });
});
