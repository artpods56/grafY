import type { CellGlassLook } from "./cell-glass-stage";
import { DEFAULT_CELL_GLASS_LOOK, DEFAULT_CELL_ROUTING } from "./cell-look";
import type { CellRoutingOptions } from "./cell-model";
import { PIPE_FAMILIES } from "./pipe-visuals";

export type CanvasLabSettings = CellGlassLook & CellRoutingOptions;

export const DEFAULT_CANVAS_LAB: CanvasLabSettings = {
  ...DEFAULT_CELL_GLASS_LOOK,
  ...DEFAULT_CELL_ROUTING,
};

type Choice<Value extends string = string> = { value: Value; label: string };
type NumericRange = { min: number; max: number; step: number; scale?: number };
type ControlCodec = {
  key: string;
  label: string;
  encode: (settings: CanvasLabSettings) => string;
  decode: (value: string) => Partial<CanvasLabSettings>;
};
type Control = ControlCodec &
  (
    | { kind: "choice"; options: readonly Choice[] }
    | { kind: "number"; range: NumericRange }
  );

function choice<Key extends keyof CanvasLabSettings>(
  field: Key,
  key: string,
  label: string,
  options: readonly Choice<CanvasLabSettings[Key] & string>[],
): Control {
  return {
    key,
    label,
    kind: "choice",
    options,
    encode: (settings) => String(settings[field]),
    decode: (value) => {
      const option = options.find((entry) => entry.value === value);
      return option ? { [field]: option.value } : {};
    },
  };
}

const ON_OFF = [
  { value: "1", label: "On" },
  { value: "0", label: "Off" },
];

function toggle(field: "grid" | "depth", label: string): Control {
  return {
    key: field,
    label,
    kind: "choice",
    options: ON_OFF,
    encode: (settings) => (settings[field] ? "1" : "0"),
    decode: (value) =>
      value === "1" || value === "0" ? { [field]: value === "1" } : {},
  };
}

function range(
  field: "blur" | "frost" | "cardFill",
  key: string,
  label: string,
  bounds: NumericRange,
): Control {
  const scale = bounds.scale ?? 1;
  return {
    key,
    label,
    kind: "number",
    range: bounds,
    encode: (settings) => String(Number((settings[field] * scale).toFixed(8))),
    decode: (value) => {
      if (!/^-?\d+(?:\.\d+)?$/.test(value)) return {};
      const number = Number(value);
      if (!Number.isFinite(number)) return {};
      return {
        [field]: Math.max(bounds.min, Math.min(bounds.max, number)) / scale,
      };
    },
  };
}

function options<const Value extends string>(
  ...values: Value[]
): Choice<Value>[] {
  return values.map((value) => ({
    value,
    label: value.charAt(0).toUpperCase() + value.slice(1),
  }));
}

export const CANVAS_LAB_SECTIONS = [
  {
    id: "appearance",
    title: "Card appearance",
    scope: "canvas",
    dev: true,
    controls: [
      choice("material", "glass", "Glass", options("liquid", "frost")),
      choice("well", "well", "Wells", options("recessed", "flat", "punched")),
      choice("corners", "corners", "Corners", options("rounded", "sharp")),
      choice("stackStyle", "stack", "Stack style", options("fan", "deck")),
      range("blur", "blur", "Blur", { min: 0, max: 12, step: 0.1 }),
      range("frost", "frost", "Frost", { min: 0, max: 0.9, step: 0.05 }),
      range("cardFill", "fill", "Card fill", {
        min: 20,
        max: 100,
        step: 2,
        scale: 100,
      }),
      toggle("grid", "Cell grid"),
    ],
  },
  {
    id: "routing",
    title: "Pipe routing",
    scope: "canvas",
    dev: true,
    controls: [
      choice("pipe", "pipe", "Pipe", PIPE_FAMILIES),
      choice("exits", "exits", "Pipe exits", options("side", "free")),
      choice("underCards", "under", "Under cards", [
        { value: "free", label: "Free" },
        { value: "gaps", label: "Prefer gaps" },
        { value: "avoid", label: "Avoid" },
      ]),
      toggle("depth", "Depth layers"),
    ],
  },
] satisfies readonly {
  id: string;
  title: string;
  scope: "canvas";
  dev: boolean;
  controls: readonly Control[];
}[];

const controls = CANVAS_LAB_SECTIONS.flatMap((section) => section.controls);

export function readCanvasLab(
  value: string | null,
  defaults = DEFAULT_CANVAS_LAB,
): CanvasLabSettings {
  const settings = { ...defaults };
  if (!value?.startsWith("1:")) return settings;
  const fields = new Map<string, string>();
  for (const pair of value.slice(2).split(",")) {
    const [key, field, extra] = pair.split(":");
    if (key && field !== undefined && extra === undefined) {
      fields.set(key, field);
    }
  }
  for (const control of controls) {
    const field = fields.get(control.key);
    if (field !== undefined) Object.assign(settings, control.decode(field));
  }
  return settings;
}

export function encodeCanvasLab(
  settings: CanvasLabSettings,
  defaults = DEFAULT_CANVAS_LAB,
): string {
  const fields = controls.flatMap((control) => {
    const value = control.encode(settings);
    return value === control.encode(defaults)
      ? []
      : [`${control.key}:${value}`];
  });
  return fields.length ? `1:${fields.join(",")}` : "1";
}

export function canvasLabHelp(): string {
  return controls
    .map((control) => {
      const values =
        control.kind === "choice"
          ? control.options.map((option) => option.value).join("|")
          : `${control.range.min}–${control.range.max}`;
      return `${control.key}:${values}`;
    })
    .join(", ");
}
