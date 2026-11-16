"use client";

import { useEffect, useRef, useState } from "react";
import type OpenSeadragon from "openseadragon";
import * as stylex from "@stylexjs/stylex";
import {
  ChevronLeft,
  ChevronRight,
  Maximize,
  Minus,
  Plus,
  RotateCw,
} from "lucide-react";
import { IconButton } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import {
  getImageInfo,
  imagePath,
  imageThumbnailUrl,
  imageTileUrl,
  type ImageInfo,
} from "@/lib/api/images";
import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  root: {
    position: "relative",
    width: "100%",
    height: "100%",
    backgroundColor: tokens.colorSurface,
  },
  viewport: { position: "absolute", inset: 0 },
  thumbnail: {
    position: "absolute",
    width: "100%",
    height: "100%",
    objectFit: "contain",
  },
  controls: {
    position: "absolute",
    bottom: 4,
    left: 4,
    right: 4,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    backgroundColor: tokens.colorSurface,
    borderRadius: tokens.radiusSm,
    fontSize: tokens.fontSizeXs,
  },
  status: {
    position: "absolute",
    top: 4,
    left: 4,
    right: 4,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    padding: 6,
  },
});

export function imageFailure(status: number): string {
  if (status === 503 || status === 501)
    return "Image service unavailable. Try again shortly.";
  if (status === 401 || status === 403 || status === 404)
    return "This image is no longer available to you.";
  if (status === 415 || status === 422) return "This file cannot be displayed.";
  return "Could not load this image. Try again.";
}

export function TiffArtifactView({
  workspaceId,
  artifactId,
  name,
}: {
  workspaceId: string;
  artifactId: string;
  name: string;
}) {
  const [page, setPage] = useState(0);
  const [attempt, setAttempt] = useState(0);
  return (
    <TiffPage
      key={`${workspaceId}:${artifactId}:${page}:${attempt}`}
      path={imagePath(workspaceId, artifactId)}
      page={page}
      name={name}
      onPage={setPage}
      onRetry={() => setAttempt(attempt + 1)}
    />
  );
}

function TiffPage({
  path,
  page,
  name,
  onPage,
  onRetry,
}: {
  path: string;
  page: number;
  name: string;
  onPage: (page: number) => void;
  onRetry: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<OpenSeadragon.Viewer | null>(null);
  const [info, setInfo] = useState<ImageInfo | null>(null);
  const [thumbnailReady, setThumbnailReady] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getImageInfo(path, page, controller.signal)
      .then(setInfo)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            imageFailure(failure instanceof ApiError ? failure.status : 0),
          );
      });
    return () => controller.abort();
  }, [path, page]);

  useEffect(() => {
    if (!info || !thumbnailReady) return;
    let disposed = false;
    import("openseadragon")
      .then(({ default: osd }) => {
        if (disposed || !host.current) return;
        const instance = osd({
          element: host.current,
          showNavigationControl: false,
          showNavigator: false,
          loadTilesWithAjax: true,
          ajaxWithCredentials: true,
          imageLoaderLimit: 4,
          immediateRender: true,
          blendTime: 0,
          animationTime: 0.2,
          visibilityRatio: 1,
          constrainDuringPan: true,
          maxZoomPixelRatio: 2,
          gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: true },
          tileSources: {
            width: info.width,
            height: info.height,
            tileSize: info.tile_size,
            minLevel: info.min_level,
            maxLevel: info.max_level,
            tileOverlap: 0,
            getTileUrl: (z: number, x: number, y: number) =>
              imageTileUrl(path, page, {
                z,
                x,
                y,
                extension: info.tile_format,
              }),
          },
        });
        viewer.current = instance;
        instance.addHandler("tile-loaded", () => setLoaded(true));
        instance.addHandler("tile-load-failed", (event) =>
          setError(imageFailure(event.tileRequest?.status ?? 0)),
        );
      })
      .catch(() => {
        if (!disposed) setError(imageFailure(0));
      });
    return () => {
      disposed = true;
      viewer.current?.destroy();
      viewer.current = null;
    };
  }, [info, thumbnailReady, path, page]);

  return (
    <section
      aria-label={`${name} scan`}
      className="nodrag nopan nowheel"
      {...stylex.props(s.root)}
    >
      {!loaded && (
        <img /* eslint-disable-line @next/next/no-img-element -- authenticated thumbnail */
          src={imageThumbnailUrl(path, page)}
          alt={name}
          {...stylex.props(s.thumbnail)}
          onLoad={() => setThumbnailReady(true)}
          onError={() => setThumbnailReady(true)}
        />
      )}
      <div
        ref={host}
        data-tiff-viewport
        data-page={page}
        {...stylex.props(s.viewport)}
      />
      {error || !loaded ? (
        <div role="status" {...stylex.props(s.status)}>
          {error ?? "Loading image…"}
        </div>
      ) : null}
      <div {...stylex.props(s.controls)}>
        <IconButton
          size="2xs"
          label="Zoom out"
          onClick={() => viewer.current?.viewport.zoomBy(0.5)}
        >
          <Minus size={14} />
        </IconButton>
        <IconButton
          size="2xs"
          label="Zoom in"
          onClick={() => viewer.current?.viewport.zoomBy(2)}
        >
          <Plus size={14} />
        </IconButton>
        <IconButton
          size="2xs"
          label="Fit image"
          onClick={() => viewer.current?.viewport.goHome()}
        >
          <Maximize size={14} />
        </IconButton>
        {info && info.page_count > 1 && (
          <>
            <IconButton
              size="2xs"
              label="Previous page"
              disabled={page === 0}
              onClick={() => onPage(page - 1)}
            >
              <ChevronLeft size={14} />
            </IconButton>
            <span>
              Page {page + 1} of {info.page_count}
            </span>
            <IconButton
              size="2xs"
              label="Next page"
              disabled={page + 1 === info.page_count}
              onClick={() => onPage(page + 1)}
            >
              <ChevronRight size={14} />
            </IconButton>
          </>
        )}
        {error && (
          <IconButton size="2xs" label="Retry image" onClick={onRetry}>
            <RotateCw size={14} />
          </IconButton>
        )}
      </div>
    </section>
  );
}
