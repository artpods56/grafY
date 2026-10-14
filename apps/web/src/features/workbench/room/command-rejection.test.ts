import { describe, expect, it } from "vitest";

import { describeCommandRejection } from "./command-rejection";
import type { GraphCommandRejectedMessage } from "./protocol";

function rejection(
  errorCode: string,
  detail = "Server detail for the rejection",
): GraphCommandRejectedMessage {
  return {
    protocol_version: 1,
    type: "graph.command.rejected",
    command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    error_code: errorCode,
    detail,
    command_index: 0,
    current_room_epoch: null,
    current_sequence: null,
  };
}

describe("describeCommandRejection", () => {
  it("names a stale compare-and-set as a concurrent edit", () => {
    expect(describeCommandRejection(rejection("field_conflict"))).toBe(
      "Someone else changed this at the same time. The latest graph has been reloaded.",
    );
  });

  it("names each missing entity as something someone else removed", () => {
    for (const code of [
      "missing_node",
      "missing_edge",
      "missing_origin",
      "missing_viewer",
      "missing_annotation",
    ]) {
      expect(describeCommandRejection(rejection(code))).toBe(
        "Something you edited was removed by someone else. The latest graph has been reloaded.",
      );
    }
  });

  it("names each duplicate as an item that already exists", () => {
    for (const code of [
      "duplicate_node",
      "duplicate_edge",
      "duplicate_origin",
    ]) {
      expect(describeCommandRejection(rejection(code))).toBe(
        "That item already exists. The latest graph has been reloaded.",
      );
    }
  });

  it("falls back to the server detail for any other code", () => {
    expect(describeCommandRejection(rejection("head_conflict"))).toBe(
      "Server detail for the rejection",
    );
    expect(describeCommandRejection(rejection("invalid_document"))).toBe(
      "Server detail for the rejection",
    );
  });

  it("falls back to a generic line when the detail is empty", () => {
    expect(describeCommandRejection(rejection("invalid_document", ""))).toBe(
      "A collaborative edit was rejected.",
    );
  });
});
