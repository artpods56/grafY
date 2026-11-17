import * as React from "react";

interface GraphAutosaveOptions {
  enabled: boolean;
  dirty: boolean;
  fingerprint: string;
  save: () => Promise<void>;
}

export function useGraphAutosave({
  enabled,
  dirty,
  fingerprint,
  save,
}: GraphAutosaveOptions): void {
  const saveRef = React.useRef(save);
  const attemptedRef = React.useRef<string | null>(null);
  React.useLayoutEffect(() => {
    saveRef.current = save;
  }, [save]);

  React.useEffect(() => {
    if (!dirty) attemptedRef.current = null;
    if (!enabled || !dirty || attemptedRef.current === fingerprint) return;
    const timer = window.setTimeout(() => {
      // The lifecycle reports failures. Leave retry to an edit or manual Save
      // rather than continuously resubmitting a rejected document.
      attemptedRef.current = fingerprint;
      void saveRef.current();
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [enabled, dirty, fingerprint]);
}
