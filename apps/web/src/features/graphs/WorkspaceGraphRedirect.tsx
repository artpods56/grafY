"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ThresholdStatus } from "@/components/threshold-status";
import { useAuthSession } from "@/features/auth/AuthSessionBoundary";
import { resolveSelectedWorkspace } from "@/features/workspaces/WorkspaceLayout";
import { useWorkspaces } from "@/hooks/use-api";

import {
  readRequestedLocation,
  searchForChosenLocation,
  serializeGraphBrowserSearch,
} from "./browser-filters";

/**
 * `/` and `/graphs` own no list of their own: they pick a location and hand the
 * person to `/workspaces/{slug}/graphs`. The address is how they say which
 * location and which filters, so both travel. `?location=atlas&q=intake&view=all`
 * opens the intake search across all of Atlas, and a parameter this route does
 * not recognise is carried along untouched rather than dropped on the floor.
 *
 * A slug in the address is a request, not a fact. It is matched against the
 * locations this person can actually reach, once those have loaded; a slug that
 * names none of them — a renamed team, a revoked invitation, a bookmark from
 * last quarter — is set aside and the usual location is opened. The route never
 * sends anyone to an address it could not confirm they can read.
 *
 * `useSearchParams` sits behind a Suspense boundary because both entry routes
 * are prerendered: the address is only known in the browser.
 */
export function WorkspaceGraphRedirect() {
  return (
    <React.Suspense fallback={<OpeningGraphs />}>
      <GraphEntryRedirect />
    </React.Suspense>
  );
}

function GraphEntryRedirect() {
  const router = useRouter();
  const { session } = useAuthSession();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const { data: workspaces, error, mutate } = useWorkspaces(session.user_id);

  React.useEffect(() => {
    if (!workspaces) return;
    const requested = readRequestedLocation(new URLSearchParams(search));
    const workspace =
      (requested
        ? workspaces.find((candidate) => candidate.slug === requested)
        : undefined) ??
      resolveSelectedWorkspace(workspaces, undefined) ??
      workspaces[0];
    if (!workspace) {
      router.replace("/workspaces");
      return;
    }
    const carried = serializeGraphBrowserSearch(
      searchForChosenLocation(new URLSearchParams(search)),
    );
    router.replace(
      `/workspaces/${encodeURIComponent(workspace.slug)}/graphs${carried}`,
    );
  }, [router, search, workspaces]);

  if (error) {
    return (
      <ThresholdStatus
        title="Workspaces couldn't be loaded"
        detail="Grafy could not determine which workspace to open."
        action={
          <button type="button" onClick={() => void mutate()}>
            Try again
          </button>
        }
      />
    );
  }

  return <OpeningGraphs />;
}

function OpeningGraphs() {
  return (
    <ThresholdStatus
      title="Opening graphs"
      detail="Selecting your workspace…"
      loading
    />
  );
}

export default WorkspaceGraphRedirect;
