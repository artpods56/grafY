"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Map as MapIcon } from "lucide-react";
import useSWR from "swr";

import { getArtifactGeoRender, type ArtifactSummary } from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";

import type { ArtifactViewerInteractionContext } from "../artifact-interactions";

import { GeoMapPreview } from "./geo-map/GeoMapPreview";
import { mapInteractionProps } from "./geo-map/map-interaction-props";
import { s } from "./geo-map/styles";

type GeoMapRendererProps = {
  artifact: Pick<ArtifactSummary, "artifact_id">;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
  autoLoad?: boolean;
  presentation?: "inspector" | "canvas";
};

function GeoMapRendererState({
  artifact,
  mode,
  availableHeight,
  interaction,
  autoLoad = false,
  presentation = autoLoad ? "canvas" : "inspector",
}: GeoMapRendererProps) {
  const { workspace } = useWorkspaceContext();
  const [loadRequested, setLoadRequested] = React.useState(
    autoLoad || presentation === "canvas",
  );
  const onUnload =
    presentation === "inspector" ? () => setLoadRequested(false) : undefined;
  const renderKey = loadRequested
    ? (["geo-artifact-render", workspace.id, artifact.artifact_id] as const)
    : null;
  const {
    data: descriptor,
    error,
    isLoading,
    mutate,
  } = useSWR(renderKey, ([, workspaceId, artifactId]) =>
    getArtifactGeoRender(workspaceId, artifactId),
  );

  if (!loadRequested) {
    return (
      <div {...mapInteractionProps(stylex.props(s.shell))}>
        <div {...stylex.props(s.placeholder)}>
          <div {...stylex.props(s.placeholderContent)}>
            <MapIcon
              size={26}
              aria-hidden="true"
              {...stylex.props(s.placeholderIcon)}
            />
            <span {...stylex.props(s.placeholderTitle)}>GIS preview ready</span>
            <span {...stylex.props(s.placeholderCopy)}>
              Load the render descriptor when you want to inspect this artifact.
            </span>
            <Button
              variant="primary"
              size="md"
              onClick={() => setLoadRequested(true)}
            >
              Load interactive map
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div {...mapInteractionProps(stylex.props(s.shell))}>
        <div {...stylex.props(s.placeholder)}>
          <div {...stylex.props(s.placeholderContent)}>
            <Notice
              tone="danger"
              action={
                <>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void mutate()}
                  >
                    Retry
                  </Button>
                  {onUnload ? (
                    <Button variant="secondary" size="sm" onClick={onUnload}>
                      Unload
                    </Button>
                  ) : null}
                </>
              }
            >
              <span {...stylex.props(s.noticeLines)}>
                <span {...stylex.props(s.placeholderTitle)}>
                  GIS preview unavailable
                </span>
                <span {...stylex.props(s.placeholderCopy)}>
                  The render descriptor could not be loaded.
                </span>
              </span>
            </Notice>
          </div>
        </div>
      </div>
    );
  }

  if (isLoading || !descriptor) {
    return (
      <div {...mapInteractionProps(stylex.props(s.shell))}>
        <div {...stylex.props(s.placeholder)}>
          <Notice tone="neutral">Loading GIS render descriptor…</Notice>
        </div>
      </div>
    );
  }

  if (mode === "raw") {
    return (
      <div {...stylex.props(s.rawShell)}>
        <div {...stylex.props(s.rawHeader)}>
          <span {...stylex.props(s.rawMeta)}>
            {descriptor.kind} · {descriptor.layers.length}{" "}
            {descriptor.layers.length === 1 ? "layer" : "layers"}
          </span>
          {onUnload ? (
            <Button size="xs" variant="secondary" onClick={onUnload}>
              Unload
            </Button>
          ) : null}
        </div>
        <pre {...stylex.props(s.raw)}>
          {JSON.stringify(descriptor, null, 2)}
        </pre>
      </div>
    );
  }

  return (
    <GeoMapPreview
      descriptor={descriptor}
      availableHeight={availableHeight}
      onUnload={onUnload}
      interaction={interaction}
    />
  );
}

export function GeoMapArtifactRenderer({
  artifact,
  ...props
}: GeoMapRendererProps & { payload?: unknown }) {
  return (
    <GeoMapRendererState
      key={artifact.artifact_id}
      artifact={artifact}
      {...props}
    />
  );
}
