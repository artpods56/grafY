// @vitest-environment jsdom
import * as React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderHook } from "../test/renderHook";
import { useGraphAutosave } from "./useGraphAutosave";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

async function advance(ms: number) {
  await React.act(async () => vi.advanceTimersByTimeAsync(ms));
}

it("saves the latest edit once after editing pauses", async () => {
  const firstSave = vi.fn().mockResolvedValue(undefined);
  const latestSave = vi.fn().mockResolvedValue(undefined);
  const props = {
    enabled: true,
    dirty: true,
    fingerprint: "a",
    save: firstSave,
  };
  const hook = await renderHook(useGraphAutosave, props);
  await advance(750);
  await hook.rerender({ ...props, fingerprint: "b", save: latestSave });
  await advance(750);
  expect(latestSave).not.toHaveBeenCalled();
  await advance(250);
  expect(firstSave).not.toHaveBeenCalled();
  expect(latestSave).toHaveBeenCalledTimes(1);
  await advance(5000);
  expect(latestSave).toHaveBeenCalledTimes(1);
});

it("waits while saving, running, disconnected or read-only and resumes when enabled", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const props = { enabled: false, dirty: true, fingerprint: "a", save };
  const hook = await renderHook(useGraphAutosave, props);
  await advance(2000);
  expect(save).not.toHaveBeenCalled();
  await hook.rerender({ ...props, enabled: true });
  await advance(1000);
  expect(save).toHaveBeenCalledTimes(1);
  await hook.rerender({ ...props, enabled: true, fingerprint: "b" });
  await advance(500);
  await hook.rerender({ ...props, fingerprint: "b" });
  await advance(1000);
  expect(save).toHaveBeenCalledTimes(1);
  await hook.rerender({ ...props, enabled: true, fingerprint: "b" });
  await advance(1000);
  expect(save).toHaveBeenCalledTimes(2);
});

it("does not loop on a failed save and allows the next edit to save", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const props = { enabled: true, dirty: true, fingerprint: "a", save };
  const hook = await renderHook(useGraphAutosave, props);
  await advance(1000);
  await hook.rerender({ ...props, enabled: false });
  await hook.rerender(props);
  await advance(5000);
  expect(save).toHaveBeenCalledTimes(1);
  await hook.rerender({ ...props, fingerprint: "b" });
  await advance(1000);
  expect(save).toHaveBeenCalledTimes(2);
});

it("cancels pending saves on unmount and never saves a clean draft", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const props = { enabled: true, dirty: false, fingerprint: "a", save };
  const hook = await renderHook(useGraphAutosave, props);
  await advance(2000);
  expect(save).not.toHaveBeenCalled();
  await hook.rerender({ ...props, dirty: true });
  await hook.unmount();
  await advance(2000);
  expect(save).not.toHaveBeenCalled();
});
