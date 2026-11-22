/**
 * Pure state-machine reducer contract.
 *
 * A reducer receives the current state, an action, and an `exec` callback to
 * declare side effects as plain data, and returns the next state without
 * performing any I/O, timers, or DOM writes.
 */
export type ExecEffect<TEffect> = (effect: TEffect) => void;

export type EffectReducer<TState, TAction, TEffect> = (
  state: TState,
  action: TAction,
  exec: ExecEffect<TEffect>,
) => TState;

export interface EffectTransition<TState, TEffect> {
  readonly state: TState;
  readonly effects: readonly TEffect[];
}

/** Run one reducer step and collect emitted effects in emission order. */
export function runEffectReducer<TState, TAction, TEffect>(
  reducer: EffectReducer<TState, TAction, TEffect>,
  state: TState,
  action: TAction,
): EffectTransition<TState, TEffect> {
  const effects: TEffect[] = [];
  const nextState = reducer(state, action, (effect) => {
    effects.push(effect);
  });
  return { state: nextState, effects };
}

/** Fold a sequence of actions left-to-right and collect all emitted effects. */
export function runEffectSequence<TState, TAction, TEffect>(
  reducer: EffectReducer<TState, TAction, TEffect>,
  initialState: TState,
  actions: readonly TAction[],
): EffectTransition<TState, TEffect> {
  let state = initialState;
  const effects: TEffect[] = [];
  const exec: ExecEffect<TEffect> = (effect) => {
    effects.push(effect);
  };
  for (const action of actions) {
    state = reducer(state, action, exec);
  }
  return { state, effects };
}
