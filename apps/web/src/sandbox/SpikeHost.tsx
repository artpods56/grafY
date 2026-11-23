"use client";

import type { ReactElement } from "react";

import type { SpikeId } from "./catalog";
import { CellCanvasSpike } from "./spikes/cell-canvas/CellCanvasSpike";
import { PortTypesSpike } from "./spikes/port-types/PortTypesSpike";
import { UiKitSpike } from "./spikes/ui-kit/UiKitSpike";

const HOSTS: Record<SpikeId, () => ReactElement> = {
  "port-types": PortTypesSpike,
  "cell-canvas": CellCanvasSpike,
  "ui-kit": UiKitSpike,
};

export function SpikeHost({ spikeId }: { spikeId: SpikeId }) {
  const Spike = HOSTS[spikeId];
  return <Spike />;
}
