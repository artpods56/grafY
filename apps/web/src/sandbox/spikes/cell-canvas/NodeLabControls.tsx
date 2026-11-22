"use client";

import * as stylex from "@stylexjs/stylex";
import { Checkbox } from "@/components/ui/checkbox";
import { Select } from "@/components/ui/select";
import { CanvasLabRow } from "@/features/workbench/cell-canvas/CanvasLabPanel";
import { replaceLabQuery } from "@/features/workbench/cell-canvas/CanvasLabProvider";
import {
  cellPortKey,
  type CellCardModel,
} from "@/features/workbench/cell-canvas/cell-model";
import { nodeFixtures, readNodeIds } from "../../fixtures/graphs/canvas-nodes";

const s = stylex.create({
  group: { display: "grid", gap: "8px" },
});

export function cardPortAddress(
  cardId: string,
  port: CellCardModel["ports"][number],
) {
  return `port:${cardId}/${cellPortKey(port.direction, port.id)}`;
}

function setNodeVisible(id: string, visible: boolean) {
  replaceLabQuery((query) => {
    const ids = new Set(readNodeIds(query.get("nodes")));
    if (visible) ids.add(id);
    else {
      ids.delete(id);
      if (query.get("sel") === id) query.delete("sel");
      for (const key of ["hot", "hover"]) {
        if (query.get(key)?.startsWith(`port:${id}/`)) query.delete(key);
      }
    }
    query.set(
      "nodes",
      nodeFixtures
        .filter((node) => ids.has(node.id))
        .map((node) => node.id)
        .join(","),
    );
  });
}

export function NodeLabControls({
  cards,
  selectedId,
  hotAddress,
}: {
  cards: readonly CellCardModel[];
  selectedId: string | null;
  hotAddress: string | null;
}) {
  const portsByCard = cards.filter((card) => card.ports.length > 0);
  const highlight = portsByCard.some((card) =>
    card.ports.some((port) => cardPortAddress(card.id, port) === hotAddress),
  )
    ? hotAddress
    : "";
  return (
    <>
      <CanvasLabRow label="Visible nodes">
        <div role="group" aria-label="Visible nodes" {...stylex.props(s.group)}>
          {nodeFixtures.map(({ id, title }) => (
            <Checkbox
              key={id}
              label={title}
              phoneTouch
              checked={cards.some((card) => card.id === id)}
              onCheckedChange={(visible) => setNodeVisible(id, visible)}
            />
          ))}
        </div>
      </CanvasLabRow>
      {cards.length > 0 && (
        <>
          <CanvasLabRow label="Selected node">
            <Select
              aria-label="Selected node"
              size="sm"
              value={selectedId ?? ""}
              onChange={(event) => {
                const value = event.currentTarget.value;
                replaceLabQuery((query) => {
                  if (value) query.set("sel", value);
                  else query.delete("sel");
                });
              }}
            >
              <option value="">None</option>
              {cards.map((card) => (
                <option key={card.id} value={card.id}>
                  {card.title}
                </option>
              ))}
            </Select>
          </CanvasLabRow>
          {portsByCard.length > 0 && (
            <CanvasLabRow label="Highlighted port">
              <Select
                aria-label="Highlighted port"
                size="sm"
                value={highlight ?? ""}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  replaceLabQuery((query) => {
                    query.delete("hover");
                    if (value) query.set("hot", value);
                    else query.delete("hot");
                  });
                }}
              >
                <option value="">None</option>
                {portsByCard.map((card) => (
                  <optgroup key={card.id} label={card.title}>
                    {card.ports.map((port) => {
                      const address = cardPortAddress(card.id, port);
                      return (
                        <option key={address} value={address}>
                          {port.name} · {port.direction}
                        </option>
                      );
                    })}
                  </optgroup>
                ))}
              </Select>
            </CanvasLabRow>
          )}
        </>
      )}
    </>
  );
}
