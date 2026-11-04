import { vi } from "vitest";

vi.mock("@/lib/stylex/tokens.stylex", () => ({
  tokens: {
    colorAccent: "#000000",
    colorSurface: "#ffffff",
  },
}));

/**
 * Vitest does not run the StyleX Babel plugin, so the real `stylex.create`
 * throws at runtime. This substitution keeps each rule's *name*, which is what
 * the assertions in `src/components/ui/*.test.tsx` compare, and returns the
 * joined names from `props` the way the compiled output would. Every test file
 * gets it: a file that wants to assert on a class name already can, and one
 * that does not care simply ignores the class names it is handed.
 *
 * `keyframes`, `defaultMarker`, `when` and `defineVars` are stubbed because
 * application code calls them (see `grep -o 'stylex\.[a-z]' src`); without an
 * entry here the namespace member is `undefined` and the module under test
 * throws on import.
 *
 * One file overrides this mock on purpose:
 * `src/features/workbench/canvas/nodes/artifact-renderers.test.tsx` compares
 * raw `renderToStaticMarkup` strings, where any class name is a difference.
 */
vi.mock("@stylexjs/stylex", () => ({
  create: <Styles extends Record<string, object>>(styles: Styles) =>
    Object.fromEntries(
      Object.entries(styles).map(([name, style]) => [
        name,
        { ...style, __styleName: name },
      ]),
    ) as Styles,
  defineVars: <Variables>(variables: Variables) => variables,
  keyframes: () => "keyframes",
  defaultMarker: () => ({}),
  when: { ancestor: (selector: string) => selector },
  props: (
    ...styles: Array<{ __styleName?: string } | null | false | undefined>
  ) => ({
    className: styles
      .flatMap((style) =>
        style && style.__styleName ? [style.__styleName] : [],
      )
      .join(" "),
  }),
}));

/**
 * jsdom 26 has no `PointerEvent` constructor, and Base UI's Radio forwards its
 * click to the hidden input with `new (ownerWindow(input).PointerEvent)(...)`
 * (radio/root/RadioRoot.mjs:138). Without the constructor that handler throws
 * and the group value never changes, so no click can be tested at all. This
 * shim gives Base UI the constructor it asks for; it changes no behaviour of
 * the component.
 *
 * The `MouseEvent` guard is what makes this safe to run everywhere: the suite
 * defaults to `environment: "node"`, where `class X extends MouseEvent` is a
 * ReferenceError in every file that never asked for a DOM.
 */
if (typeof MouseEvent !== "undefined" && !("PointerEvent" in globalThis)) {
  class PointerEventShim extends MouseEvent {}
  Object.assign(globalThis, { PointerEvent: PointerEventShim });
}
