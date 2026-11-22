import { expect, it } from "vitest";
import { SPIKES, getSpike } from "./catalog";

it("registers each sandbox experiment under a unique id with a design question", () => {
  expect(new Set(SPIKES.map(({ id }) => id)).size).toBe(SPIKES.length);
  for (const entry of SPIKES) {
    expect(entry.question.trim()).toMatch(/\?$/);
    expect(getSpike(entry.id)).toBe(entry);
  }
  expect(getSpike("missing")).toBeUndefined();
});
