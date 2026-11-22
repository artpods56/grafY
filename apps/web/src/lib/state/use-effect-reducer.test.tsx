// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EffectReducer } from "./effect-reducer";
import { useEffectReducer, type EffectHandler } from "./use-effect-reducer";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type TestState = {
  readonly value: number;
  readonly log: readonly string[];
};

type TestAction =
  | { readonly kind: "add"; readonly amount: number }
  | { readonly kind: "ping"; readonly note: string }
  | { readonly kind: "trigger_reentrant" }
  | { readonly kind: "reentrant_done" };

type TestEffect =
  | { readonly kind: "record"; readonly label: string; readonly value: number }
  | { readonly kind: "follow_up" };

const testReducer: EffectReducer<TestState, TestAction, TestEffect> = (
  state,
  action,
  exec,
) => {
  switch (action.kind) {
    case "add": {
      const value = state.value + action.amount;
      exec({ kind: "record", label: "add", value });
      return { value, log: [...state.log, `add:${action.amount}`] };
    }
    case "ping":
      exec({ kind: "record", label: action.note, value: state.value });
      return state;
    case "trigger_reentrant":
      exec({ kind: "follow_up" });
      return { ...state, log: [...state.log, "triggered"] };
    case "reentrant_done":
      exec({ kind: "record", label: "done", value: state.value });
      return { ...state, log: [...state.log, "done"] };
  }
};

describe("useEffectReducer", () => {
  const roots: Array<{ root: Root; container: HTMLElement }> = [];

  afterEach(() => {
    for (const { root, container } of roots.splice(0)) {
      React.act(() => {
        root.unmount();
      });
      container.remove();
    }
    document.body.replaceChildren();
  });

  function mountHarness({
    initialFactory = () => ({ value: 10, log: [] }),
    onEffect,
    strict = false,
  }: {
    initialFactory?: () => TestState;
    onEffect: EffectHandler<TestEffect, TestAction>;
    strict?: boolean;
  }) {
    let latestState: TestState | null = null;
    let latestDispatch: React.Dispatch<TestAction> | null = null;

    function Harness({
      handler,
    }: {
      handler: EffectHandler<TestEffect, TestAction>;
    }) {
      const [state, dispatch] = useEffectReducer(
        testReducer,
        initialFactory,
        handler,
      );
      React.useEffect(() => {
        latestState = state;
        latestDispatch = dispatch;
      });
      return <div data-value={String(state.value)}>{state.log.join(",")}</div>;
    }

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push({ root, container });

    const renderWith = (handler: EffectHandler<TestEffect, TestAction>) => {
      const node = <Harness handler={handler} />;
      React.act(() => {
        root.render(
          strict ? <React.StrictMode>{node}</React.StrictMode> : node,
        );
      });
    };

    renderWith(onEffect);

    return {
      container,
      getState: () => latestState!,
      dispatch: (action: TestAction) => latestDispatch!(action),
      rerender: renderWith,
    };
  }

  it("supports a lazy initializer and runs effects after commit", () => {
    const init = vi.fn<() => TestState>(() => ({ value: 5, log: [] }));
    const seen: TestEffect[] = [];

    const harness = mountHarness({
      initialFactory: init,
      onEffect: (effect) => {
        seen.push(effect);
      },
    });

    expect(harness.getState()).toEqual({ value: 5, log: [] });
    expect(init).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([]);

    React.act(() => {
      harness.dispatch({ kind: "add", amount: 3 });
    });

    expect(harness.getState()).toEqual({ value: 8, log: ["add:3"] });
    expect(seen).toEqual([{ kind: "record", label: "add", value: 8 }]);
  });

  it("updates stateRef synchronously across sequential batched dispatches", () => {
    const seen: TestEffect[] = [];
    const harness = mountHarness({
      onEffect: (effect) => {
        seen.push(effect);
      },
    });

    React.act(() => {
      harness.dispatch({ kind: "add", amount: 2 });
      harness.dispatch({ kind: "add", amount: 4 });
    });

    expect(harness.getState()).toEqual({
      value: 16,
      log: ["add:2", "add:4"],
    });
    expect(seen).toEqual([
      { kind: "record", label: "add", value: 12 },
      { kind: "record", label: "add", value: 16 },
    ]);
  });

  it("flushes effects even when state identity does not change", () => {
    const seen: TestEffect[] = [];
    const harness = mountHarness({
      onEffect: (effect) => {
        seen.push(effect);
      },
    });

    React.act(() => {
      harness.dispatch({ kind: "ping", note: "same-state" });
    });

    expect(harness.getState()).toEqual({ value: 10, log: [] });
    expect(seen).toEqual([{ kind: "record", label: "same-state", value: 10 }]);
  });

  it("supports re-entrant dispatch from inside runEffect", () => {
    const seen: TestEffect[] = [];
    const harness = mountHarness({
      onEffect: (effect, dispatch) => {
        seen.push(effect);
        if (effect.kind === "follow_up") {
          dispatch({ kind: "reentrant_done" });
        }
      },
    });

    React.act(() => {
      harness.dispatch({ kind: "trigger_reentrant" });
    });

    expect(harness.getState()).toEqual({
      value: 10,
      log: ["triggered", "done"],
    });
    expect(seen).toEqual([
      { kind: "follow_up" },
      { kind: "record", label: "done", value: 10 },
    ]);
  });

  it("uses the latest runEffect closure after re-render", () => {
    const firstHandler = vi.fn();
    const secondHandler = vi.fn();

    const harness = mountHarness({ onEffect: firstHandler });
    harness.rerender(secondHandler);

    React.act(() => {
      harness.dispatch({ kind: "ping", note: "fresh-closure" });
    });

    expect(firstHandler).not.toHaveBeenCalled();
    expect(secondHandler).toHaveBeenCalledTimes(1);
    expect(secondHandler).toHaveBeenCalledWith(
      { kind: "record", label: "fresh-closure", value: 10 },
      expect.any(Function),
    );
  });

  it("fires emitted effects once under React.StrictMode", () => {
    const seen: TestEffect[] = [];
    const harness = mountHarness({
      strict: true,
      onEffect: (effect) => {
        seen.push(effect);
      },
    });

    React.act(() => {
      harness.dispatch({ kind: "add", amount: 7 });
    });

    expect(harness.getState()).toEqual({ value: 17, log: ["add:7"] });
    expect(seen).toEqual([{ kind: "record", label: "add", value: 17 }]);
  });
});
