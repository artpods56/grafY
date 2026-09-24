// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMediaQuery } from "./use-media-query";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<Root>();

afterEach(async () => {
  for (const root of mountedRoots) {
    await React.act(async () => root.unmount());
  }
  mountedRoots.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("useMediaQuery", () => {
  it("moves its subscription when the requested query changes", async () => {
    const queryStates = new Map<
      string,
      {
        listeners: Set<EventListener>;
        mediaQuery: MediaQueryList;
        setMatches(matches: boolean): void;
      }
    >();
    const matchMedia = vi.fn((query: string): MediaQueryList => {
      const existing = queryStates.get(query);
      if (existing) return existing.mediaQuery;

      const listeners = new Set<EventListener>();
      let matches = false;
      const mediaQuery = {
        get matches() {
          return matches;
        },
        media: query,
        onchange: null,
        addEventListener: ((_type: string, listener: EventListener) => {
          listeners.add(listener);
        }) as MediaQueryList["addEventListener"],
        removeEventListener: ((_type: string, listener: EventListener) => {
          listeners.delete(listener);
        }) as MediaQueryList["removeEventListener"],
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      };
      const state = {
        listeners,
        mediaQuery,
        setMatches(nextMatches: boolean) {
          matches = nextMatches;
        },
      };
      queryStates.set(query, state);
      return mediaQuery;
    });
    vi.stubGlobal("matchMedia", matchMedia);
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    mountedRoots.add(root);

    function Status({ query }: { query: string }) {
      const mobile = useMediaQuery(query);
      return <output>{mobile ? "mobile" : "desktop"}</output>;
    }

    const phoneQuery = "(max-width: 720px)";
    const pointerQuery = "(pointer: fine)";
    await React.act(async () => root.render(<Status query={phoneQuery} />));
    expect(container.textContent).toBe("desktop");
    expect(queryStates.get(phoneQuery)?.listeners).toHaveLength(1);

    const phoneState = queryStates.get(phoneQuery);
    expect(phoneState).toBeDefined();
    if (!phoneState) throw new Error("Phone media query was not created");
    phoneState.setMatches(true);
    await React.act(async () => {
      for (const listener of phoneState.listeners)
        listener(new Event("change"));
    });
    expect(container.textContent).toBe("mobile");

    await React.act(async () => root.render(<Status query={pointerQuery} />));
    expect(container.textContent).toBe("desktop");
    expect(phoneState.listeners).toHaveLength(0);
    expect(queryStates.get(pointerQuery)?.listeners).toHaveLength(1);

    await React.act(async () => root.unmount());
    mountedRoots.delete(root);
    expect(queryStates.get(pointerQuery)?.listeners).toHaveLength(0);
  });
});
