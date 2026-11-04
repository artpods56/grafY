import { describe, it, expect } from "vitest";
import { appendDelta, parseDelta } from "./stream";
const frame = {
  graph_id: "g",
  agent_id: "a",
  conversation_id: "c",
  turn_id: "t",
  message_id: "m",
  offset: 0,
  text: "😀",
};
describe("Agent streaming", () => {
  it("accepts the first chunk and counts Python code points", () => {
    const first = appendDelta(null, frame);
    expect(
      appendDelta(first, { ...frame, offset: 1, text: " answer" }).text,
    ).toBe("😀 answer");
  });
  it("ignores duplicate chunks", () => {
    const first = appendDelta(null, frame);
    expect(appendDelta(first, frame)).toEqual(first);
  });
  it("freezes missing and out of order chunks until snapshot", () => {
    const gap = appendDelta(null, { ...frame, offset: 2 });
    expect(gap.gap).toBe(true);
    expect(appendDelta(gap, frame).text).toBe("");
  });
  it("does not mix message or turn identities", () => {
    expect(
      appendDelta(appendDelta(null, frame), {
        ...frame,
        turn_id: "other",
        offset: 1,
      }).text,
    ).toBe("😀");
  });
  it("validates external frames", () => {
    expect(parseDelta({ ...frame, type: "agent.delta" })).toEqual(frame);
    expect(
      parseDelta({ ...frame, type: "agent.delta", offset: -1 }),
    ).toBeNull();
    expect(parseDelta({ ...frame, type: "agent.delta", text: 3 })).toBeNull();
  });
});
