# Kit lab — what to change when the kit changes

`/sandbox/ui-kit` (`src/sandbox/spikes/ui-kit/UiKitSpike.tsx`) draws every part of
`src/components/ui` at every size and variant the types declare. The first cut
read badly, and the reason is worth keeping: it is the reason any "show me all
the components" page reads badly, so the next pass should not re-derive it.

## What the app actually uses

`bun apps/web/src/sandbox/spikes/ui-kit/usage.mjs` prints this table by walking
every opening tag in `apps/web/src` (tests and the sandbox excluded). Numbers are
a snapshot from 2026-11-23; rerun the command rather than trusting them.

| component               | sites | chosen explicitly                                                                     | left to the default     |
| ----------------------- | ----- | ------------------------------------------------------------------------------------- | ----------------------- |
| Button `variant`        | 114   | `secondary` 43, `ghost` 25, `primary` 22, `danger` 8, `soft` 6, `dashed` 4, `plain` 3 | 3 (default `secondary`) |
| Button `size`           | 114   | `xs` 55, `lg` 26, `sm` 22, `md` 7, `text` 3                                           | 1 (default `md`)        |
| IconButton `variant`    | 69    | `ghost` 21, `soft` 6, `danger` 3, `accent` 1                                          | 38 (default `ghost`)    |
| IconButton `size`       | 69    | `2xs` 27, `sm` 9, `lg` 8, `xs` 7, `md` 5                                              | 13 (default `sm`)       |
| Notice `variant`        | 29    | `banner` 2, `inline` 1                                                                | 26 (default `inline`)   |
| Field `size`            | 29    | `dense` 8                                                                             | 21                      |
| Select `size`           | 15    | `dense` 7                                                                             | 8                       |
| Slider `size`           | 12    | `dense` 11                                                                            | 1                       |
| SegmentedControl `size` | 7     | `sm` 5                                                                                | 2                       |
| Switch `size`           | 7     | `dense` 5, `sm` 1                                                                     | 1                       |
| ColorField `size`       | 6     | `dense` 6                                                                             | 0                       |
| ButtonLink              | 2     | `ghost` 1, `secondary` 1; `xs` 2                                                      | 0                       |
| Checkbox                | 1     | —                                                                                     | 1                       |

Three things fall out of it:

- The app's button vocabulary is three variants and two sizes. `plain`, `text`
  and `dashed` together are 10 of 114 choices.
- `IconButton` has never once been rendered `primary`.
- `dense` is the in-card step and it is used consistently: every Slider, every
  ColorField, most Selects and Switches. If a future change moves `dense`, it
  moves the whole canvas, not one call site.

## Why the first cut reads badly

1. **Every cell gets equal weight.** A 7×5 matrix gives ButtonLink — 2 call sites
   in the product — the same wall of chips as Button, and renders a full column
   of `primary` icon buttons that nothing has ever used. About a third of the
   page is dead weight shouting as loudly as the three cells that are the app.
2. **Nothing is a reference point.** Sizes float free, so 22px versus 26px is a
   guess, and no number is printed anywhere. A control means nothing until it is
   against the 300px card or the 360px side panel it lives in.
3. **The page has no frame.** Its own notes are 11.5px muted and its headings
   15px — the same register as the specimens — and each section lays out on its
   own `auto-fit` count, so there is no column to scan down. Chrome and specimen
   sit in one plane, which is the same defect the node credentials popover had.

## The next cut

- One row per component, ordered by the table above rather than by file name.
- Left cell names it, gives its call-site count and two real paths.
- Then only the options in use, at real size, with measured pixels printed under
  each. Unused options collapse to a footnote line.
- Each control shown once in context: a card header, a side-panel row, a dialog
  footer. That is the comparison anyone is actually making.
- Specimens inside `Surface tone="sunken"` frames, so the lab stops competing
  with what it is showing.
- Keep a full matrix as a second-class section — it earns its place when someone
  adds a variant and wants to see where it lands, not when someone picks one.

The size lists in the spike stay literal rather than derived from the union
types. A derived list stays green when a variant is added; a literal one leaves a
visible hole in the page, which is the point of the page.

## Two kit defects the lab turned up

Neither is fixed by the lab; both are candidates the next time someone touches
`src/components/ui`.

- `IconButton` documents `title={null}` as the way to silence a tooltip that only
  repeats visible text (`button.tsx:58`), but `title` intersects with Base UI's
  `title?: string`, which collapses `null` out, so it does not typecheck. No call
  site in the repo passes null; the documented escape hatch is unreachable.
- `ColorWell.block` defaults to `true` (`color-field.tsx:92`) while its docstring
  offers "stay a small square (a toolbar)". The square is therefore the case that
  must opt out, which is the opposite of what the text implies.
