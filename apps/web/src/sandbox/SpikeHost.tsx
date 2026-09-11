"use client";

import type { ReactElement } from "react";

import type { SpikeId } from "./catalog";
import { DrawerInteractionSpike } from "./spikes/drawer-interaction/DrawerInteractionSpike";
import { PortInspectorSpike } from "./spikes/port-inspector/PortInspectorSpike";
import { ViewerLinkSpike } from "./spikes/viewer-link/ViewerLinkSpike";

const HOSTS: Record<SpikeId, () => ReactElement> = {
  "port-inspector": PortInspectorSpike,
  "viewer-link": ViewerLinkSpike,
  "drawer-interaction": DrawerInteractionSpike,
};

export function SpikeHost({ spikeId }: { spikeId: SpikeId }) {
  const Spike = HOSTS[spikeId];
  return <Spike />;
}
