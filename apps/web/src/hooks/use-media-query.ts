"use client";

import * as React from "react";

export const FINE_POINTER_QUERY = "(pointer: fine)";

export function useMediaQuery(query: string): boolean {
  const media = React.useMemo(
    () =>
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia(query)
        : null,
    [query],
  );
  const subscribe = React.useCallback(
    (listener: () => void) => {
      if (!media) return () => undefined;

      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    },
    [media],
  );
  const getSnapshot = React.useCallback(() => media?.matches ?? false, [media]);

  return React.useSyncExternalStore(subscribe, getSnapshot, () => false);
}
