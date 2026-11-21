export const SPIKES = [
  {
    id: "port-types",
    title: "Port types",
    summary:
      "Where a generic port's type lives: six approaches on the same nodes, from a caption to a function signature.",
  },
  {
    id: "drawer-interaction",
    title: "Canvas with real input plugs",
    summary:
      "The product canvas with real node cards, kept as a base for building an input interaction.",
  },
  {
    id: "underground-pipes",
    title: "Pipes under the canvas",
    summary:
      "Edges as angular pipes laid under a translucent canvas, surfacing through sockets at the ports.",
  },
  {
    id: "cell-canvas",
    title: "Cell-based canvas",
    summary:
      "Cards, ports, gutters, and pipes on one shared 50px cell grid with snapping drag and track-capacity routing.",
  },
] as const;

export type SpikeId = (typeof SPIKES)[number]["id"];

export function getSpike(id: string): (typeof SPIKES)[number] | undefined {
  return SPIKES.find((spike) => spike.id === id);
}
