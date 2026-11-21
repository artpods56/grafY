import type { PipeRoutingBackend } from "../pipe-routing";
import { corridorRouter } from "./corridor";
import { elbowRouter } from "./elbow";
import { octilinearRouter } from "./octilinear";

/** Every router the panel offers, the default first. */
export const PIPE_ROUTERS = [
  elbowRouter,
  corridorRouter,
  octilinearRouter,
] as const;

export type PipeRouterId = (typeof PIPE_ROUTERS)[number]["id"];

export const DEFAULT_PIPE_ROUTER: PipeRouterId = "elbow";

export function pipeRouter(id: PipeRouterId): PipeRoutingBackend {
  return PIPE_ROUTERS.find((router) => router.id === id) ?? elbowRouter;
}
