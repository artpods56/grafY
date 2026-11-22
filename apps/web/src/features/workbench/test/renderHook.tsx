import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

interface HookResult<Value> {
  readonly current: Value;
}

interface RenderedHook<Props, Value> {
  result: HookResult<Value>;
  rerender: (props: Props) => Promise<void>;
  unmount: () => Promise<void>;
}

const mountedRoots = new Map<Root, HTMLElement>();
const hookValueUnset = Symbol("hook-value-unset");

afterEach(async () => {
  for (const [root, container] of mountedRoots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  mountedRoots.clear();
});

export async function renderHook<Props, Value>(
  useValue: (props: Props) => Value,
  initialProps: Props,
): Promise<RenderedHook<Props, Value>> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.set(root, container);
  let current: Value | typeof hookValueUnset = hookValueUnset;

  function HookProbe({ props }: { props: Props }) {
    current = useValue(props);
    return null;
  }

  await React.act(async () => {
    root.render(<HookProbe props={initialProps} />);
  });

  return {
    result: {
      get current() {
        if (current === hookValueUnset) {
          throw new Error("Hook did not render a value");
        }
        return current;
      },
    },
    async rerender(props) {
      await React.act(async () => {
        root.render(<HookProbe props={props} />);
      });
    },
    async unmount() {
      if (!mountedRoots.has(root)) return;
      await React.act(async () => root.unmount());
      mountedRoots.delete(root);
      container.remove();
    },
  };
}
