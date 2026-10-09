"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Layers3, LocateFixed, RotateCcw, X } from "lucide-react";
import maplibregl from "maplibre-gl";
import useSWR from "swr";

import {
  queryArtifactGeoFeatures,
  type GeoRenderDescriptor,
  type GeoRenderLayer,
} from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";

import type {
  ArtifactViewerActivity,
  ArtifactViewerInteractionContext,
} from "../../artifact-interactions";

import { LayerInspector } from "./LayerInspector";
import {
  applyInteractionOverrides,
  applyLayerOverrides,
} from "./layer-overrides";
import {
  categoryLayerId,
  cloneLayer,
  layerId,
  layerRenderIds,
} from "./layer-identity";
import { mapInteractionProps } from "./map-interaction-props";
import {
  createGeoMapStyle,
  ensurePmtilesProtocol,
  fitBounds,
  normalizedMapBounds,
} from "./map-style";
import { s } from "./styles";
import {
  DEFAULT_LABEL_STYLE,
  FEATURE_HIT_RADIUS,
  MAP_FIT_OPTIONS,
  type SelectedGeoFeature,
} from "./style-constants";

maplibregl.workerUrl = "/maplibre-gl-csp-worker.js";

export function GeoMapPreview({
  descriptor,
  availableHeight,
  onUnload,
  interaction,
}: {
  descriptor: GeoRenderDescriptor;
  availableHeight?: number;
  onUnload: () => void;
  interaction?: ArtifactViewerInteractionContext;
}) {
  const { workspace } = useWorkspaceContext();
  const workspaceId = workspace.id;
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<maplibregl.Map | null>(null);
  const [layers, setLayers] = React.useState(() =>
    descriptor.layers.map(cloneLayer),
  );
  const [inspectorOpen, setInspectorOpen] = React.useState(false);
  const [expandedLayerId, setExpandedLayerId] = React.useState<string | null>(
    null,
  );
  const [mapReady, setMapReady] = React.useState(false);
  const [mapError, setMapError] = React.useState<string | null>(null);
  const [selectedFeature, setSelectedFeature] =
    React.useState<SelectedGeoFeature | null>(null);
  const layersRef = React.useRef(layers);
  const interactionRef = React.useRef(interaction);
  const focusedSelectionRef = React.useRef<{
    map: maplibregl.Map;
    signature: string;
  } | null>(null);
  const inspectorId = React.useId();
  const focusBindings =
    interaction?.incoming.filter((binding) =>
      binding.effects.includes("focus"),
    ) ?? [];
  const focusRows = focusBindings.flatMap((binding) => binding.rows);
  const unmappedFocusSelectionCount = focusBindings.reduce(
    (count, binding) =>
      count + Math.max(0, binding.sourceSelectionCount - binding.rows.length),
    0,
  );
  const focusSignature = JSON.stringify(focusRows);
  const focusKey = focusRows.length
    ? ([
        "geo-artifact-focus",
        workspaceId,
        descriptor.artifact_id,
        focusSignature,
      ] as const)
    : null;
  const {
    data: focusResult,
    error: focusError,
    isValidating: focusLoading,
    mutate: retryFocus,
  } = useSWR(focusKey, ([, keyWorkspaceId, artifactId]) =>
    queryArtifactGeoFeatures(keyWorkspaceId, artifactId, {
      rows: focusRows.map((values) => ({ values })),
    }),
  );

  React.useEffect(() => {
    layersRef.current = layers;
  }, [layers]);

  React.useEffect(() => {
    interactionRef.current = interaction;
  }, [interaction]);

  React.useEffect(() => {
    if (!interaction) return;
    const fields = new Map<
      string,
      { id: string; title: string; valueType: string }
    >();
    for (const layer of descriptor.layers) {
      if (layer.source.kind !== "vector") continue;
      for (const field of layer.source.fields ?? []) {
        fields.set(field.id, {
          id: field.id,
          title: field.title,
          valueType: field.value_type,
        });
      }
    }
    interaction.onFieldsChange([...fields.values()]);
  }, [descriptor.layers, interaction]);

  React.useEffect(() => {
    if (!containerRef.current) return;
    ensurePmtilesProtocol();
    const interactiveLayerIds = descriptor.layers.flatMap((layer) => {
      if (layer.style.kind === "vector") {
        return [
          layerId(layer, "fill"),
          layerId(layer, "line"),
          layerId(layer, "point"),
        ];
      }
      if (layer.style.kind === "categorized_points") {
        return layer.style.categories.map((category) =>
          categoryLayerId(layer, category, "point"),
        );
      }
      return [];
    });
    let map: maplibregl.Map;
    try {
      const mapOptions: maplibregl.MapOptions = {
        container: containerRef.current,
        style: createGeoMapStyle(workspaceId, descriptor, layersRef.current),
        attributionControl: true,
      };
      const initialBounds = normalizedMapBounds(descriptor.initial_bounds);
      if (initialBounds) {
        mapOptions.bounds = initialBounds;
        mapOptions.fitBoundsOptions = { ...MAP_FIT_OPTIONS, duration: 0 };
      } else {
        mapOptions.center = [0, 18];
        mapOptions.zoom = 1.25;
      }
      map = new maplibregl.Map(mapOptions);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "The browser could not initialize the interactive map";
      const errorTimer = window.setTimeout(() => setMapError(message), 0);
      return () => window.clearTimeout(errorTimer);
    }
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    const renderedFeaturesAt = (event: maplibregl.MapMouseEvent) => {
      const canvas = map.getCanvas();
      const displayedBounds = canvas.getBoundingClientRect();
      const scaleX =
        displayedBounds.width > 0 && canvas.clientWidth > 0
          ? canvas.clientWidth / displayedBounds.width
          : 1;
      const scaleY =
        displayedBounds.height > 0 && canvas.clientHeight > 0
          ? canvas.clientHeight / displayedBounds.height
          : 1;
      const canvasIsScaled =
        Math.abs(scaleX - 1) > 0.001 || Math.abs(scaleY - 1) > 0.001;
      // React Flow scales the viewer with CSS while MapLibre queries its
      // unscaled canvas coordinate system.
      const point: [number, number] = [
        event.point.x * scaleX,
        event.point.y * scaleY,
      ];
      // Keep sparse points easy to select without making their visual markers larger.
      const queryBounds: [maplibregl.PointLike, maplibregl.PointLike] = [
        [
          point[0] - FEATURE_HIT_RADIUS * scaleX,
          point[1] - FEATURE_HIT_RADIUS * scaleY,
        ],
        [
          point[0] + FEATURE_HIT_RADIUS * scaleX,
          point[1] + FEATURE_HIT_RADIUS * scaleY,
        ],
      ];
      const renderedLayerIds = interactiveLayerIds.filter((id) =>
        map.getLayer(id),
      );
      const features = renderedLayerIds.length
        ? map.queryRenderedFeatures(queryBounds, { layers: renderedLayerIds })
        : [];
      return {
        features,
        lngLat: canvasIsScaled ? map.unproject(point) : event.lngLat,
      };
    };
    map.on("mousemove", (event) => {
      map
        .getCanvasContainer()
        .classList.toggle(
          "maplibregl-track-pointer",
          renderedFeaturesAt(event).features.length > 0,
        );
    });
    map.on("mouseout", () => {
      map.getCanvasContainer().classList.remove("maplibregl-track-pointer");
    });
    map.on("dragstart", () => {
      map.getCanvasContainer().classList.remove("maplibregl-track-pointer");
    });
    map.on("click", (event) => {
      const { features, lngLat } = renderedFeaturesAt(event);
      const feature = features[0];
      if (!feature) {
        setSelectedFeature(null);
        interactionRef.current?.onSelectionChange({
          kind: "key-selection",
          items: [],
        });
        return;
      }

      const ownerLayer = layersRef.current.find((layer) =>
        layerRenderIds(layer).includes(feature.layer.id),
      );
      const rawProperties: Record<string, unknown> =
        feature.properties && typeof feature.properties === "object"
          ? feature.properties
          : {};
      const titleProperty =
        ownerLayer?.style.kind === "vector" ||
        ownerLayer?.style.kind === "categorized_points"
          ? (ownerLayer.style.label?.property ?? DEFAULT_LABEL_STYLE.property)
          : DEFAULT_LABEL_STYLE.property;
      const titleValue = rawProperties[titleProperty];
      const featureId =
        feature.id === undefined || feature.id === null
          ? null
          : String(feature.id);
      const properties = Object.entries(rawProperties)
        .map(([name, rawValue]) => {
          let value: string;
          if (rawValue === null) {
            value = "null";
          } else if (
            typeof rawValue === "string" ||
            typeof rawValue === "number" ||
            typeof rawValue === "boolean"
          ) {
            value = String(rawValue);
          } else {
            value = JSON.stringify(rawValue) ?? String(rawValue);
          }
          return { name, value };
        })
        .sort((left, right) => left.name.localeCompare(right.name));
      const selectionValues = Object.fromEntries(
        Object.entries(rawProperties).flatMap(([name, value]) =>
          value === null ||
          typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean"
            ? [[name, value]]
            : [],
        ),
      );
      const title =
        typeof titleValue === "string" && titleValue.trim()
          ? titleValue
          : featureId
            ? `Feature ${featureId}`
            : `${feature.geometry.type} feature`;

      setInspectorOpen(false);
      setSelectedFeature({
        layerId: ownerLayer?.id ?? feature.layer.id,
        layerTitle: ownerLayer?.title ?? "Map feature",
        title,
        geometryType: feature.geometry.type,
        featureId,
        longitude: lngLat.lng,
        latitude: lngLat.lat,
        properties,
        selectionValues,
      });
      interactionRef.current?.onSelectionChange({
        kind: "key-selection",
        items: [{ values: selectionValues }],
      });
    });
    map.on("load", () => {
      setMapReady(true);
      applyLayerOverrides(map, layersRef.current);
    });
    map.on("error", (event) => {
      const message = event.error?.message;
      if (message) setMapError(message);
    });
    return () => {
      mapRef.current = null;
      map.getCanvasContainer().classList.remove("maplibregl-track-pointer");
      map.remove();
    };
  }, [descriptor, workspaceId]);

  React.useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map?.isStyleLoaded()) return;
    applyInteractionOverrides(map, layers, interaction?.incoming ?? []);
  }, [interaction?.incoming, layers, mapReady]);

  React.useEffect(() => {
    if (!focusRows.length) {
      focusedSelectionRef.current = null;
      return;
    }
    const map = mapRef.current;
    if (
      !mapReady ||
      !map?.isStyleLoaded() ||
      !focusResult?.bounds ||
      (focusedSelectionRef.current?.map === map &&
        focusedSelectionRef.current.signature === focusSignature)
    ) {
      return;
    }
    fitBounds(map, focusResult.bounds, true);
    focusedSelectionRef.current = { map, signature: focusSignature };
  }, [focusResult?.bounds, focusRows.length, focusSignature, mapReady]);

  React.useEffect(() => {
    mapRef.current?.resize();
  }, [availableHeight]);

  const updateLayer = (index: number, next: GeoRenderLayer) => {
    setSelectedFeature((current) =>
      current?.layerId === next.id ? null : current,
    );
    setLayers((current) =>
      current.map((layer, currentIndex) =>
        currentIndex === index ? next : layer,
      ),
    );
  };

  const moveLayer = (index: number, direction: -1 | 1) => {
    setLayers((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      const moved = next[index];
      const neighbour = next[nextIndex];
      if (!moved || !neighbour) return current;
      next[index] = neighbour;
      next[nextIndex] = moved;
      return next;
    });
  };

  const viewerActivity = React.useMemo<ArtifactViewerActivity | null>(() => {
    if (mapError) {
      return {
        state: "error",
        title: "Map rendering failed",
        message: mapError,
      };
    }
    if (!mapReady) {
      return {
        state: "working",
        title: "Loading interactive map",
        message: "Preparing map layers.",
      };
    }
    if (focusError) {
      const detail =
        focusError instanceof Error
          ? focusError.message
          : "The map query failed.";
      return {
        state: "error",
        title: "Linked selection lookup failed",
        message: detail,
        retry: () => void retryFocus(),
      };
    }
    if (focusLoading) {
      return {
        state: "working",
        title: "Locating linked selection",
        message: "Searching the map layers for matching features.",
      };
    }
    if (unmappedFocusSelectionCount > 0 && focusRows.length === 0) {
      return {
        state: "warning",
        title: "Selection mapping failed",
        message:
          "The selected row does not provide all configured target fields.",
      };
    }
    if (focusResult?.matched_feature_count === 0) {
      return {
        state: "warning",
        title: "No linked feature found",
        message: "No map feature matched the linked selection.",
      };
    }
    if (
      focusResult &&
      focusResult.matched_feature_count > 0 &&
      !focusResult.bounds
    ) {
      const featureLabel =
        focusResult.matched_feature_count === 1 ? "feature" : "features";
      return {
        state: "warning",
        title: "Linked feature has no geometry",
        message: `Matched ${focusResult.matched_feature_count} ${featureLabel}, but no geometry was available to focus.`,
      };
    }
    if (focusResult?.matched_feature_count === 1) {
      return {
        state: unmappedFocusSelectionCount > 0 ? "warning" : "success",
        title: "Linked feature located",
        message: "Located 1 matching map feature.",
      };
    }
    if (focusResult && focusResult.matched_feature_count > 1) {
      return {
        state: "warning",
        title: "Multiple linked features located",
        message: `Located ${focusResult.matched_feature_count} matches; showing their combined extent.`,
      };
    }
    return null;
  }, [
    focusError,
    focusLoading,
    focusResult,
    focusRows.length,
    mapError,
    mapReady,
    retryFocus,
    unmappedFocusSelectionCount,
  ]);

  React.useEffect(() => {
    interaction?.onActivityChange(viewerActivity);
    return () => interaction?.onActivityChange(null);
  }, [interaction, viewerActivity]);

  return (
    <div
      data-grafy-geo-map="true"
      {...mapInteractionProps(stylex.props(s.shell))}
      style={{ height: Math.max(320, availableHeight ?? 420) }}
    >
      <div
        ref={containerRef}
        aria-label="Interactive GIS map. Click a feature to inspect its properties."
        {...mapInteractionProps(stylex.props(s.map))}
      />
      <div {...stylex.props(s.mapControls)}>
        <button
          type="button"
          aria-expanded={inspectorOpen}
          aria-controls={inspectorId}
          {...mapInteractionProps(stylex.props(s.utilityButton))}
          onClick={() => {
            setSelectedFeature(null);
            setInspectorOpen((open) => !open);
          }}
        >
          <Layers3 size={13} aria-hidden="true" />
          {layers.length} {layers.length === 1 ? "layer" : "layers"}
        </button>
        <button
          type="button"
          disabled={!descriptor.initial_bounds}
          aria-label="Fit descriptor bounds"
          title={
            descriptor.initial_bounds
              ? "Fit descriptor bounds"
              : "No descriptor bounds"
          }
          {...mapInteractionProps(stylex.props(s.utilityButton))}
          onClick={() => {
            const map = mapRef.current;
            if (map) fitBounds(map, descriptor.initial_bounds, true);
          }}
        >
          <LocateFixed size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Unload interactive map"
          title="Unload interactive map"
          {...mapInteractionProps(stylex.props(s.utilityButton))}
          onClick={onUnload}
        >
          <X size={13} aria-hidden="true" />
        </button>
      </div>
      {inspectorOpen ? (
        <div
          id={inspectorId}
          role="region"
          aria-label="Map layer inspector"
          {...mapInteractionProps(stylex.props(s.inspector))}
        >
          <div {...stylex.props(s.inspectorHeader)}>
            <span {...stylex.props(s.inspectorTitle)}>Layer inspector</span>
            <button
              type="button"
              {...stylex.props(s.resetButton)}
              onClick={() => setLayers(descriptor.layers.map(cloneLayer))}
            >
              <RotateCcw size={11} aria-hidden="true" />
              Reset all
            </button>
          </div>
          {layers.map((layer, index) => (
            <LayerInspector
              key={layer.id}
              layer={layer}
              index={index}
              count={layers.length}
              expanded={expandedLayerId === layer.id}
              onExpandedChange={() =>
                setExpandedLayerId((current) =>
                  current === layer.id ? null : layer.id,
                )
              }
              onChange={(next) => updateLayer(index, next)}
              onMove={(direction) => moveLayer(index, direction)}
              onReset={() => {
                const original = descriptor.layers.find(
                  (candidate) => candidate.id === layer.id,
                );
                if (original) updateLayer(index, cloneLayer(original));
              }}
            />
          ))}
        </div>
      ) : null}
      {selectedFeature ? (
        <section
          role="region"
          aria-label="Selected feature details"
          {...mapInteractionProps(stylex.props(s.featurePanel))}
        >
          <header {...stylex.props(s.featureHeader)}>
            <span {...stylex.props(s.featureHeading)}>
              <span {...stylex.props(s.featureKicker)}>
                {selectedFeature.layerTitle} · {selectedFeature.geometryType}
              </span>
              <span {...stylex.props(s.featureTitle)}>
                {selectedFeature.title}
              </span>
              <span {...stylex.props(s.featureMeta)}>
                {selectedFeature.featureId
                  ? `ID ${selectedFeature.featureId} · `
                  : ""}
                {selectedFeature.longitude.toFixed(5)},{" "}
                {selectedFeature.latitude.toFixed(5)}
              </span>
            </span>
            <button
              type="button"
              aria-label="Close feature details"
              title="Close feature details"
              {...mapInteractionProps(stylex.props(s.iconButton))}
              onClick={() => {
                setSelectedFeature(null);
                interaction?.onSelectionChange({
                  kind: "key-selection",
                  items: [],
                });
              }}
            >
              <X size={13} aria-hidden="true" />
            </button>
          </header>
          {selectedFeature.properties.length ? (
            <dl {...stylex.props(s.featureProperties)}>
              {selectedFeature.properties.map((property) => (
                <div key={property.name} {...stylex.props(s.featureProperty)}>
                  <dt
                    title={property.name}
                    {...stylex.props(s.featurePropertyName)}
                  >
                    {property.name}
                  </dt>
                  <dd {...stylex.props(s.featurePropertyValue)}>
                    {property.value}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p {...stylex.props(s.featureEmpty)}>
              This feature has no properties.
            </p>
          )}
        </section>
      ) : null}
    </div>
  );
}
