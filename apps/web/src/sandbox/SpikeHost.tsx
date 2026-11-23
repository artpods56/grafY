"use client";

import type { ReactElement } from "react";

import type { SpikeId } from "./catalog";
import { CellCanvasSpike } from "./spikes/cell-canvas/CellCanvasSpike";
import { CredentialsSpike } from "./spikes/credentials/CredentialsSpike";
import { PortTypesSpike } from "./spikes/port-types/PortTypesSpike";
import { StudioThemeSpike } from "./spikes/studio-theme/StudioThemeSpike";
import { UiKitSpike } from "./spikes/ui-kit/UiKitSpike";

const HOSTS: Record<SpikeId, () => ReactElement> = {
  "port-types": PortTypesSpike,
  "cell-canvas": CellCanvasSpike,
  "ui-kit": UiKitSpike,
  "studio-theme": StudioThemeSpike,
  credentials: CredentialsSpike,
};

export function SpikeHost({ spikeId }: { spikeId: SpikeId }) {
  const Spike = HOSTS[spikeId];
  return <Spike />;
}
