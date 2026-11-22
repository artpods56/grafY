"use client";

import * as React from "react";

import { runEffectReducer, type EffectReducer } from "./effect-reducer";

export type EffectHandler<TEffect, TAction> = (
  effect: TEffect,
  dispatch: React.Dispatch<TAction>,
) => void;

/**
 * Thin React adapter around a pure {@link EffectReducer}.
 *
 * Dispatched actions transition immediately against `stateRef` so sequential
 * dispatches within one event handler or effect flush see up-to-date state,
 * while emitted effects flush after commit in declaration order.
 */
export function useEffectReducer<TState, TAction, TEffect>(
  reducer: EffectReducer<TState, TAction, TEffect>,
  initialState: TState | (() => TState),
  runEffect: EffectHandler<TEffect, TAction>,
): readonly [TState, React.Dispatch<TAction>] {
  const [state, setState] = React.useState<TState>(initialState);
  const [effectTick, setEffectTick] = React.useState(0);

  const stateRef = React.useRef<TState>(state);
  const reducerRef = React.useRef(reducer);
  const runEffectRef = React.useRef(runEffect);
  const pendingEffectsRef = React.useRef<TEffect[]>([]);

  React.useEffect(() => {
    reducerRef.current = reducer;
    runEffectRef.current = runEffect;
  });

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
    if (effects.length > 0) {
      pendingEffectsRef.current.push(...effects);
      setEffectTick((tick) => tick + 1);
    }
  }, []);

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
