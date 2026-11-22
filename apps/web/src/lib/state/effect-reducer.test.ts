import { describe, expect, it } from "vitest";

import {
  runEffectReducer,
  runEffectSequence,
  type EffectReducer,
} from "./effect-reducer";

type CounterState =
  | { readonly phase: "idle"; readonly count: number }
  | { readonly phase: "busy"; readonly count: number };

type CounterAction =
  | { readonly kind: "increment"; readonly delta: number }
  | { readonly kind: "start_sync" }
  | { readonly kind: "finish_sync" }
  | { readonly kind: "noop" };

type CounterEffect =
  | { readonly kind: "log"; readonly message: string }
  | { readonly kind: "sync"; readonly count: number };

const counterReducer: EffectReducer<
  CounterState,
  CounterAction,
  CounterEffect
> = (state, action, exec) => {
  switch (action.kind) {
    case "increment": {
      const nextCount = state.count + action.delta;
      exec({ kind: "log", message: `before:${state.count}` });
      exec({ kind: "log", message: `after:${nextCount}` });
      return { ...state, count: nextCount };
    }
    case "start_sync":
      if (state.phase === "busy") return state;
      exec({ kind: "sync", count: state.count });
      return { phase: "busy", count: state.count };
    case "finish_sync":
      if (state.phase === "idle") return state;
      exec({ kind: "log", message: "synced" });
      return { phase: "idle", count: state.count };
    case "noop":
      return state;
  }
};

describe("effect-reducer", () => {
  it("returns next state and preserves multiple effects in emission order", () => {
    const initial: CounterState = { phase: "idle", count: 1 };
    const result = runEffectReducer(counterReducer, initial, {
      kind: "increment",
      delta: 3,
    });

    expect(result.state).toEqual({ phase: "idle", count: 4 });
    expect(result.effects).toEqual([
      { kind: "log", message: "before:1" },
      { kind: "log", message: "after:4" },
    ]);
    expect(initial.count).toBe(1);
  });

  it("handles zero-effect transitions", () => {
    const initial: CounterState = { phase: "idle", count: 2 };
    const result = runEffectReducer(counterReducer, initial, { kind: "noop" });

    expect(result.state).toBe(initial);
    expect(result.effects).toEqual([]);
  });

  it("folds an action sequence left-to-right and accumulates effects in order", () => {
    const initial: CounterState = { phase: "idle", count: 0 };
    const result = runEffectSequence(counterReducer, initial, [
      { kind: "increment", delta: 2 },
      { kind: "start_sync" },
      { kind: "start_sync" },
      { kind: "increment", delta: 5 },
      { kind: "finish_sync" },
    ]);

    expect(result.state).toEqual({ phase: "idle", count: 7 });
    expect(result.effects).toEqual([
      { kind: "log", message: "before:0" },
      { kind: "log", message: "after:2" },
      { kind: "sync", count: 2 },
      { kind: "log", message: "before:2" },
      { kind: "log", message: "after:7" },
      { kind: "log", message: "synced" },
    ]);
  });
});
