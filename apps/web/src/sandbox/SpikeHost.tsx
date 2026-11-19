"use client";

import type { ReactElement } from "react";

import type { SpikeId } from "./catalog";
import { DrawerInteractionSpike } from "./spikes/drawer-interaction/DrawerInteractionSpike";
import { PortTypesSpike } from "./spikes/port-types/PortTypesSpike";
import { UndergroundPipesSpike } from "./spikes/underground-pipes/UndergroundPipesSpike";

const HOSTS: Record<SpikeId, () => ReactElement> = {
  "port-types": PortTypesSpike,
  "drawer-interaction": DrawerInteractionSpike,
  "underground-pipes": UndergroundPipesSpike,
};

export function SpikeHost({ spikeId }: { spikeId: SpikeId }) {
  const Spike = HOSTS[spikeId];
  return <Spike />;
}
