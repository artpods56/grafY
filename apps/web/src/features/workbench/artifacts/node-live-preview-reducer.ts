export interface NodePreviewFrame {
  readonly sequence: number;
  readonly computation_id: string;
  readonly label: string;
  readonly detail: string | null;
  readonly content_type: string;
  readonly data_url: string | null;
  readonly text: string | null;
  readonly emitted_at: string;
}

export type NodeLivePreviewStatus = "connecting" | "live" | "reconnecting";
export type NodeLivePreviewZoom = "fit" | "actual";

export interface NodeLivePreviewState {
  readonly streamKey: string;
  readonly status: NodeLivePreviewStatus;
  readonly computationId: string | null;
  readonly frames: readonly NodePreviewFrame[];
  readonly selectedIndex: number;
  readonly followLatest: boolean;
  readonly zoom: NodeLivePreviewZoom;
}

export type NodeLivePreviewAction =
  | { readonly type: "reset"; readonly streamKey: string }
  | { readonly type: "connected"; readonly streamKey: string }
  | { readonly type: "reconnecting"; readonly streamKey: string }
  | {
      readonly type: "frame";
      readonly streamKey: string;
      readonly frame: NodePreviewFrame;
    }
  | { readonly type: "select_frame"; readonly index: number }
  | { readonly type: "toggle_follow" }
  | { readonly type: "set_zoom"; readonly zoom: NodeLivePreviewZoom };

const MAX_RETAINED_FRAMES = 64;

export function nodeLivePreviewInitialState(
  streamKey: string,
): NodeLivePreviewState {
  return {
    streamKey,
    status: "connecting",
    computationId: null,
    frames: [],
    selectedIndex: 0,
    followLatest: true,
    zoom: "fit",
  };
}

export function nodeLivePreviewReducer(
  state: NodeLivePreviewState,
  action: NodeLivePreviewAction,
): NodeLivePreviewState {
  switch (action.type) {
    case "reset":
      return nodeLivePreviewInitialState(action.streamKey);

    case "connected":
      if (action.streamKey !== state.streamKey) return state;
      return { ...state, status: "live" };

    case "reconnecting":
      if (action.streamKey !== state.streamKey) return state;
      return { ...state, status: "reconnecting" };

    case "frame": {
      if (action.streamKey !== state.streamKey) return state;
      const incoming = action.frame;

      // A new computation_id means the node was re-run: replace the previous run's frames.
      if (state.computationId !== incoming.computation_id) {
        return {
          ...state,
          status: "live",
          computationId: incoming.computation_id,
          frames: [incoming],
          selectedIndex: 0,
        };
      }

      // Deduplicate replayed frames when EventSource reconnects.
      const alreadyPresent = state.frames.some(
        (existing) => existing.sequence === incoming.sequence,
      );
      if (alreadyPresent) {
        return { ...state, status: "live" };
      }

      const appended = [...state.frames, incoming];
      const overflow = Math.max(0, appended.length - MAX_RETAINED_FRAMES);
      const nextFrames = overflow > 0 ? appended.slice(overflow) : appended;
      const nextSelected = state.followLatest
        ? nextFrames.length - 1
        : Math.max(0, state.selectedIndex - overflow);

      return {
        ...state,
        status: "live",
        frames: nextFrames,
        selectedIndex: nextSelected,
      };
    }

    case "select_frame": {
      if (state.frames.length === 0) return state;
      const clamped = Math.max(
        0,
        Math.min(action.index, state.frames.length - 1),
      );
      return {
        ...state,
        selectedIndex: clamped,
        followLatest: clamped === state.frames.length - 1,
      };
    }

    case "toggle_follow": {
      const nextFollow = !state.followLatest;
      return {
        ...state,
        followLatest: nextFollow,
        selectedIndex:
          nextFollow && state.frames.length > 0
            ? state.frames.length - 1
            : state.selectedIndex,
      };
    }

    case "set_zoom":
      return { ...state, zoom: action.zoom };
  }
}
