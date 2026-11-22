"use client";

import * as React from "react";

import { runEffectReducer, type EffectReducer } from "./effect-reducer";

export type EffectHandler<TEffect, TAction> = (
  effect: TEffect,
  dispatch: React.Dispatch<TAction>,
) => void;

export interface UseEffectReducerOptions {
  readonly flush?: "effect" | "sync";
}

const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? React.useLayoutEffect : React.useEffect;

/**
 * Thin React adapter around a pure {@link EffectReducer}.
 *
 * Dispatched actions transition immediately against `stateRef` so sequential
 * dispatches within one event handler or effect flush see up-to-date state.
 * Emitted effects flush after commit by default, or synchronously inside
 * `dispatch` when `{ flush: "sync" }` is set.
 */
export function useEffectReducer<TState, TAction, TEffect>(
  reducer: EffectReducer<TState, TAction, TEffect>,
  initialState: TState | (() => TState),
  runEffect: EffectHandler<TEffect, TAction>,
  options?: UseEffectReducerOptions,
): readonly [TState, React.Dispatch<TAction>] {
  const flush = options?.flush ?? "effect";
  const [state, setState] = React.useState<TState>(initialState);
  const [effectTick, setEffectTick] = React.useState(0);

  const stateRef = React.useRef<TState>(state);
  const reducerRef = React.useRef(reducer);
  const runEffectRef = React.useRef(runEffect);
  const flushRef = React.useRef<"effect" | "sync">(flush);
  const pendingEffectsRef = React.useRef<TEffect[]>([]);
  const syncQueueRef = React.useRef<TEffect[]>([]);
  const flushingSyncRef = React.useRef(false);
  const dispatchRef = React.useRef<React.Dispatch<TAction>>(() => {});

  const dispatch = React.useCallback((action: TAction) => {
    const prev = stateRef.current;
    const { state: next, effects } = runEffectReducer(
      reducerRef.current,
      prev,
      action,
    );
    stateRef.current = next;
    if (!Object.is(next, prev)) {
      setState(next);
    }
    if (effects.length === 0) return;
    if (flushRef.current === "sync") {
      syncQueueRef.current.push(...effects);
      if (flushingSyncRef.current) return;
      flushingSyncRef.current = true;
      try {
        while (syncQueueRef.current.length > 0) {
          const effect = syncQueueRef.current.shift()!;
          runEffectRef.current(effect, dispatchRef.current);
        }
      } finally {
        syncQueueRef.current.length = 0;
        flushingSyncRef.current = false;
      }
      return;
    }
    pendingEffectsRef.current.push(...effects);
    setEffectTick((tick) => tick + 1);
  }, []);

  useIsomorphicLayoutEffect(() => {
    reducerRef.current = reducer;
    runEffectRef.current = runEffect;
    flushRef.current = flush;
    dispatchRef.current = dispatch;
  });

  React.useEffect(() => {
    void effectTick;
    if (pendingEffectsRef.current.length === 0) return;
    const batch = pendingEffectsRef.current.splice(0);
    for (const effect of batch) {
      runEffectRef.current(effect, dispatch);
    }
  }, [effectTick, dispatch]);

  return [state, dispatch] as const;
}
