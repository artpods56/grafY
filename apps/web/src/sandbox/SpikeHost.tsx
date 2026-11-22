"use client";

import type { ReactElement } from "react";

import type { SpikeId } from "./catalog";
import { CellCanvasSpike } from "./spikes/cell-canvas/CellCanvasSpike";
import { DrawerInteractionSpike } from "./spikes/drawer-interaction/DrawerInteractionSpike";
import { PortTypesSpike } from "./spikes/port-types/PortTypesSpike";

const HOSTS: Record<SpikeId, () => ReactElement> = {
  "port-types": PortTypesSpike,
  "drawer-interaction": DrawerInteractionSpike,
  "cell-canvas": CellCanvasSpike,
};

export function SpikeHost({ spikeId }: { spikeId: SpikeId }) {
  const Spike = HOSTS[spikeId];
  return <Spike />;
}
