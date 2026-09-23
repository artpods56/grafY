import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, onUnauthorized, readBrowserCookie, request } from "./client";

const csrfSentinel = "csrf-sentinel-value";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("browser API transport", () => {
  it("uses the relative same-origin base and credentials", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await request("GET", "/v1/session");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/session",
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
      }),
    );
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain(csrfSentinel);
  });

  it("parses the browser-readable CSRF cookie without matching similar names", () => {
    vi.stubGlobal("document", {
      cookie: `other=value; grafy_csrf=${encodeURIComponent(csrfSentinel)}; grafy_csrf_extra=wrong`,
    });

    expect(readBrowserCookie("grafy_csrf")).toBe(csrfSentinel);
    expect(readBrowserCookie("grafy_csrf_extra")).toBe("wrong");
  });

  it("adds the CSRF token only to unsafe requests", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(new Response("{}", { status: 200 })),
      );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: `grafy_csrf=${csrfSentinel}` });

    await request("GET", "/v1/read");
    await request("HEAD", "/v1/head");
    await request("OPTIONS", "/v1/options");
    await request("POST", "/v1/create", { body: { value: "safe" } });
    await request("TRACE", "/v1/trace");

    const calls = fetchMock.mock.calls as Array<[string, RequestInit]>;
    expect(calls).toHaveLength(5);
    expect(
      calls
        .slice(0, 3)
        .every(
          ([, init]) =>
            !(init.headers as Record<string, string>)["X-CSRF-Token"],
        ),
    ).toBe(true);
    expect(
      (calls[3]?.[1].headers as Record<string, string>)["X-CSRF-Token"],
    ).toBe(csrfSentinel);
    expect(
      (calls[4]?.[1].headers as Record<string, string>)["X-CSRF-Token"],
    ).toBe(csrfSentinel);
    expect(JSON.stringify(calls[0])).not.toContain(csrfSentinel);
    expect(JSON.stringify(calls[1])).not.toContain(csrfSentinel);
    expect(JSON.stringify(calls[2])).not.toContain(csrfSentinel);
    expect(JSON.stringify(calls[3])).toContain(csrfSentinel);
    expect(JSON.stringify(calls[4])).toContain(csrfSentinel);
  });

  it("does not fabricate a CSRF header when the cookie is absent", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: "session=opaque-session" });

    await request("POST", "/v1/create", { body: { value: "safe" } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.headers).not.toHaveProperty("X-CSRF-Token");
  });

  it("bounds and redacts error detail", async () => {
    const responseBody = JSON.stringify({
      detail: `${csrfSentinel} ${"x".repeat(10_000)}`,
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(responseBody, {
        status: 400,
        statusText: "Bad Request",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: `grafy_csrf=${csrfSentinel}` });

    let error: unknown;
    try {
      await request("POST", "/v1/create", { body: {} });
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail).not.toContain(csrfSentinel);
    expect((error as ApiError).detail.length).toBeLessThanOrEqual(2_048);
  });

  it("reads only a bounded error prefix and cancels the remaining body", async () => {
    let bytesRead = 0;
    let cancelled = false;
    const chunks = [
      `${"x".repeat(2_040)}${csrfSentinel}`,
      ...Array.from({ length: 100 }, () => "y".repeat(1_024)),
    ];
    let chunkIndex = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        const chunk = new TextEncoder().encode(chunks[chunkIndex++] ?? "");
        bytesRead += chunk.byteLength;
        controller.enqueue(chunk);
      },
      cancel() {
        cancelled = true;
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(body, {
        status: 400,
        statusText: "Bad Request",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("document", { cookie: `grafy_csrf=${csrfSentinel}` });

    let error: unknown;
    try {
      await request("POST", "/v1/create", { body: {} });
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail).not.toContain(csrfSentinel);
    expect(bytesRead).toBeLessThan(10_000);
    expect(cancelled).toBe(true);
  });

  it("signals post-auth 401 before consuming a delayed error body", async () => {
    let bodyController: ReadableStreamDefaultController<Uint8Array> | undefined;
    let notified = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        bodyController = controller;
        controller.enqueue(new TextEncoder().encode("{"));
      },
      pull() {
        return new Promise<void>(() => {});
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(body, {
        status: 401,
        statusText: "Unauthorized",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const waitForNotification = new Promise<void>((resolve) => {
      const unsubscribe = onUnauthorized(() => {
        notified = true;
        unsubscribe();
        resolve();
      });
    });

    const pendingRequest = request("GET", "/v1/protected");
    await expect(
      Promise.race([
        waitForNotification,
        new Promise((_, reject) => {
          setTimeout(
            () => reject(new Error("unauthorized notification was delayed")),
            100,
          );
        }),
      ]),
    ).resolves.toBeUndefined();
    expect(notified).toBe(true);
    bodyController?.error(new Error("stop test stream"));
    await expect(pendingRequest).rejects.toBeInstanceOf(ApiError);
  });
});
