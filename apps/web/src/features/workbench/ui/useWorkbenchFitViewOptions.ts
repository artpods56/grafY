"use client";

import * as React from "react";

import { useMediaQuery } from "@/hooks/use-media-query";

const MOBILE_WORKBENCH_QUERY = "(max-width: 720px)";

interface SafeAreaInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

const ZERO_SAFE_AREA_INSETS: SafeAreaInsets = {
  top: 0,
  right: 0,
  bottom: 0,
  left: 0,
};

const WORKBENCH_DESKTOP_FIT_VIEW_OPTIONS = {
  padding: {
    top: "90px",
    right: "48px",
    bottom: "64px",
    left: "165px",
  },
  maxZoom: 0.88,
} as const;

const WORKBENCH_MOBILE_FIT_PADDING = {
  top: 76,
  right: 20,
  bottom: 96,
  left: 20,
} as const;

/**
 * React Flow fits the canvas with a padding box, so the drawer, the activity bar, and
 * the notched-device chrome all have to be folded into that box before it is measured.
 */
function readSafeAreaInsets(): SafeAreaInsets {
  const probe = document.createElement("div");
  probe.style.cssText = [
    "position: fixed",
    "visibility: hidden",
    "pointer-events: none",
    "padding-top: env(safe-area-inset-top, 0px)",
    "padding-right: env(safe-area-inset-right, 0px)",
    "padding-bottom: env(safe-area-inset-bottom, 0px)",
    "padding-left: env(safe-area-inset-left, 0px)",
  ].join(";");
  document.body.append(probe);
  const style = window.getComputedStyle(probe);
  const insets = {
    top: Number.parseFloat(style.paddingTop) || 0,
    right: Number.parseFloat(style.paddingRight) || 0,
    bottom: Number.parseFloat(style.paddingBottom) || 0,
    left: Number.parseFloat(style.paddingLeft) || 0,
  };
  probe.remove();
  return insets;
}

function useSafeAreaInsets(enabled: boolean): SafeAreaInsets {
  const [insets, setInsets] = React.useState(ZERO_SAFE_AREA_INSETS);
  React.useLayoutEffect(() => {
    if (!enabled) return;
    const updateInsets = () => {
      const next = readSafeAreaInsets();
      setInsets((current) =>
        current.top === next.top &&
        current.right === next.right &&
        current.bottom === next.bottom &&
        current.left === next.left
          ? current
          : next,
      );
    };
    updateInsets();
    window.addEventListener("resize", updateInsets);
    window.visualViewport?.addEventListener("resize", updateInsets);
    return () => {
      window.removeEventListener("resize", updateInsets);
      window.visualViewport?.removeEventListener("resize", updateInsets);
    };
  }, [enabled]);
  return insets;
}

export function useWorkbenchFitViewOptions() {
  const mobileWorkbench = useMediaQuery(MOBILE_WORKBENCH_QUERY);
  const safeAreaInsets = useSafeAreaInsets(mobileWorkbench);

  return React.useMemo(() => {
    if (!mobileWorkbench) return WORKBENCH_DESKTOP_FIT_VIEW_OPTIONS;
    return {
      padding: {
        top: `${WORKBENCH_MOBILE_FIT_PADDING.top + safeAreaInsets.top}px`,
        right: `${WORKBENCH_MOBILE_FIT_PADDING.right + safeAreaInsets.right}px`,
        bottom: `${WORKBENCH_MOBILE_FIT_PADDING.bottom + safeAreaInsets.bottom}px`,
        left: `${WORKBENCH_MOBILE_FIT_PADDING.left + safeAreaInsets.left}px`,
      },
      maxZoom: 0.88,
    } as const;
  }, [mobileWorkbench, safeAreaInsets]);
}
