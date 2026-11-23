import { useState } from "react";

import {
  KeyRound,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Settings2,
  Trash2,
} from "lucide-react";
import * as stylex from "@stylexjs/stylex";

import { Button, ButtonLink, IconButton } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ColorField, ColorWell } from "@/components/ui/color-field";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import {
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Surface } from "@/components/ui/surface";
import { Switch } from "@/components/ui/switch";

/**
 * The kit in one place: every `src/components/ui` part at every size it
 * declares, in the states a call site actually reaches. The point is comparison
 * — what `xs` looks like beside `lg`, what `dense` costs beside `md` — which no
 * feature screen shows because each one uses two sizes and hides the rest.
 *
 * The size lists below are written out rather than derived from the types, so
 * adding a variant to the kit leaves this lab visibly incomplete instead of
 * silently skipping it.
 */

const BUTTON_VARIANTS = [
  "primary",
  "secondary",
  "soft",
  "ghost",
  "danger",
  "plain",
  "dashed",
] as const;
const BUTTON_SIZES = ["xs", "sm", "md", "lg", "text"] as const;
const ICON_VARIANTS = ["primary", "ghost", "soft", "danger", "accent"] as const;
const ICON_SIZES = ["2xs", "xs", "sm", "md", "lg"] as const;
const CONTROL_SIZES = ["md", "sm", "dense"] as const;
const NOTICE_TONES = ["neutral", "warning", "danger"] as const;
const SURFACE_TONES = ["raised", "floating", "sunken"] as const;
const SURFACE_SHAPES = ["sm", "md", "lg", "pill"] as const;
const DIALOG_SIZES = [
  "compact",
  "default",
  "form",
  "wide",
  "catalog",
  "viewport",
] as const;

const SECTIONS = [
  { id: "buttons", label: "Buttons" },
  { id: "icon-buttons", label: "Icon buttons" },
  { id: "links", label: "Links" },
  { id: "fields", label: "Fields" },
  { id: "selects", label: "Selects" },
  { id: "choices", label: "Choices" },
  { id: "segmented", label: "Segmented" },
  { id: "sliders", label: "Sliders" },
  { id: "colour", label: "Colour" },
  { id: "notices", label: "Notices" },
  { id: "surfaces", label: "Surfaces" },
  { id: "menus", label: "Menus" },
  { id: "dialogs", label: "Dialogs" },
] as const;

type DialogSize = (typeof DIALOG_SIZES)[number];

export function UiKitSpike() {
  const [pressed, setPressed] = useState(true);
  const [toggles, setToggles] = useState({ on: true, off: false });
  const [checks, setChecks] = useState({ on: true, off: false });
  const [segment, setSegment] = useState("md");
  const [opacity, setOpacity] = useState(0.42);
  const [count, setCount] = useState(6);
  const [colour, setColour] = useState("#8b5cf6");
  const [noticeOpen, setNoticeOpen] = useState(true);
  const [menuFlags, setMenuFlags] = useState({ grid: true, guides: false });
  const [menuChoice, setMenuChoice] = useState("snap");
  const [dialog, setDialog] = useState<DialogSize | null>(null);

  return (
    <div {...stylex.props(s.page)}>
      <nav {...stylex.props(s.nav)}>
        {SECTIONS.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            {...stylex.props(s.navLink)}
          >
            {section.label}
          </a>
        ))}
      </nav>

      <Section
        id="buttons"
        title="Button"
        note="7 variants × 5 sizes. `text` has no box; `plain` keeps the box. `pressed`, `swatch`, `block` and `disabled` are below the grid."
      >
        <div {...stylex.props(s.matrix)}>
          <span />
          {BUTTON_VARIANTS.map((variant) => (
            <span key={variant} {...stylex.props(s.axis)}>
              {variant}
            </span>
          ))}
          {BUTTON_SIZES.map((size) => (
            <FragmentRow key={size} label={size}>
              {BUTTON_VARIANTS.map((variant) => (
                <Button
                  key={variant}
                  size={size}
                  variant={variant}
                  xstyle={s.natural}
                >
                  <Plus size={13} />
                  {variant}
                </Button>
              ))}
            </FragmentRow>
          ))}
        </div>
        <div {...stylex.props(s.row)}>
          <Button
            variant="secondary"
            size="sm"
            pressed={pressed}
            onClick={() => setPressed((value) => !value)}
          >
            pressed: {String(pressed)}
          </Button>
          <Button variant="secondary" size="sm" swatch={colour}>
            swatch
          </Button>
          <Button variant="primary" size="sm" disabled>
            disabled
          </Button>
          <Button variant="danger" size="sm" disabled>
            disabled
          </Button>
        </div>
        <div {...stylex.props(s.half)}>
          <Button variant="dashed" size="sm" block>
            <Plus size={13} />
            block — fills the row
          </Button>
        </div>
      </Section>

      <Section
        id="icon-buttons"
        title="IconButton"
        note="5 variants × 5 sizes, plus `shape` and the pressed state. `label` is required: it becomes the accessible name and, by default, the tooltip. The docs say pass `title={null}` where the control already sits in visible text; the type rejects null, so no call site in the repo does."
      >
        <div {...stylex.props(s.matrixIcons)}>
          <span />
          {ICON_VARIANTS.map((variant) => (
            <span key={variant} {...stylex.props(s.axis)}>
              {variant}
            </span>
          ))}
          {ICON_SIZES.map((size) => (
            <FragmentRow key={size} label={size}>
              {ICON_VARIANTS.map((variant) => (
                <IconButton
                  key={variant}
                  label={`${variant} ${size}`}
                  size={size}
                  variant={variant}
                >
                  <Settings2 />
                </IconButton>
              ))}
            </FragmentRow>
          ))}
        </div>
        <div {...stylex.props(s.row)}>
          <span {...stylex.props(s.axisWide)}>states</span>
          <IconButton label="disabled" variant="ghost" size="sm" disabled>
            <Settings2 />
          </IconButton>
          <IconButton
            label="pressed"
            variant="ghost"
            size="sm"
            pressed
            onClick={() => {}}
          >
            <Settings2 />
          </IconButton>
          <IconButton
            label="with a tooltip of its own"
            title="Hover me — the label is the tooltip by default"
            variant="ghost"
            size="sm"
          >
            <Settings2 />
          </IconButton>
          <span {...stylex.props(s.axisWide)}>
            left to right: disabled, pressed, custom tooltip — ghost is quiet
            enough that the three differ only on hover
          </span>
        </div>
      </Section>

      <Section
        id="links"
        title="ButtonLink"
        note="An anchor with Button's shape, for actions that navigate rather than act."
      >
        {BUTTON_SIZES.map((size) => (
          <div key={size} {...stylex.props(s.row)}>
            {BUTTON_VARIANTS.map((variant) => (
              <ButtonLink
                key={variant}
                href="#links"
                size={size}
                variant={variant}
              >
                {variant}
              </ButtonLink>
            ))}
          </div>
        ))}
      </Section>

      <Section
        id="fields"
        title="Field · TextInput · TextArea"
        note="Two sizes. `error` replaces `description` and marks the control invalid; `aside` sits at the right of the label row."
      >
        <div {...stylex.props(s.cols)}>
          <Field label="Base URL" description="Any OpenAI-compatible endpoint.">
            <TextInput defaultValue="https://api.openai.com/v1" mono />
          </Field>
          <Field
            label="API key"
            error="The provider returned 401 for that key."
          >
            <TextInput placeholder="Paste key" type="password" />
          </Field>
          <Field
            label="Model"
            aside={<span {...stylex.props(s.aside)}>Configured</span>}
          >
            <TextInput defaultValue="gpt-4.1-mini" />
          </Field>
          <Field label="Read only" description="Disabled at the field level.">
            <TextInput defaultValue="Temperature" disabled />
          </Field>
          <Field label="System prompt" size="dense">
            <TextArea rows={3} defaultValue="dense — the canvas-card step" />
          </Field>
          <Field label="Schema" description="A JSON Schema document.">
            <TextArea rows={3} mono defaultValue={'{\n  "type": "object"\n}'} />
          </Field>
        </div>
      </Section>

      <Section id="selects" title="Select" note="Three sizes.">
        <div {...stylex.props(s.cols)}>
          {CONTROL_SIZES.map((size) => (
            <Field key={size} label={`size: ${size}`}>
              <Select defaultValue="team" size={size}>
                <option value="personal">Personal · my laptop key</option>
                <option value="team">Team gateway · ****1234</option>
              </Select>
            </Field>
          ))}
          <Field
            label="invalid"
            error="That conversation is no longer in this workspace."
          >
            <Select defaultValue="gone" invalid>
              <option value="gone">gone</option>
            </Select>
          </Field>
          <Field label="block fills the row">
            <Select block defaultValue="long">
              <option value="long">
                A long label that would otherwise size the control
              </option>
            </Select>
          </Field>
          <Field label="disabled">
            <Select defaultValue="team" disabled>
              <option value="team">Team gateway</option>
            </Select>
          </Field>
        </div>
      </Section>

      <Section
        id="choices"
        title="Checkbox · Switch"
        note="Both take three sizes and a `label` that toggles them, so a row needs no other markup. `phoneTouch` grows the hit row to 44px below the phone breakpoint and never applies inside a card."
      >
        <div {...stylex.props(s.cols)}>
          <div {...stylex.props(s.stack)}>
            {CONTROL_SIZES.map((size) => (
              <div key={size} {...stylex.props(s.row)}>
                <Checkbox
                  size={size}
                  label={`${size} on`}
                  checked={checks.on}
                  onCheckedChange={(checked) =>
                    setChecks({ ...checks, on: checked })
                  }
                />
                <Checkbox
                  size={size}
                  label="off"
                  checked={checks.off}
                  onCheckedChange={(checked) =>
                    setChecks({ ...checks, off: checked })
                  }
                />
                <Checkbox
                  size={size}
                  label="disabled"
                  checked
                  disabled
                  onCheckedChange={() => {}}
                />
              </div>
            ))}
            <Checkbox
              size="md"
              label="phoneTouch — 44px row on a phone"
              phoneTouch
              checked={checks.on}
              onCheckedChange={(checked) =>
                setChecks({ ...checks, on: checked })
              }
            />
          </div>
          <div {...stylex.props(s.stack)}>
            {CONTROL_SIZES.map((size) => (
              <div key={size} {...stylex.props(s.row)}>
                <Switch
                  size={size}
                  label={`${size} on`}
                  checked={toggles.on}
                  onCheckedChange={(checked) =>
                    setToggles({ ...toggles, on: checked })
                  }
                />
                <Switch
                  size={size}
                  label="off"
                  checked={toggles.off}
                  onCheckedChange={(checked) =>
                    setToggles({ ...toggles, off: checked })
                  }
                />
                <Switch
                  size={size}
                  label="disabled"
                  checked
                  disabled
                  onCheckedChange={() => {}}
                />
              </div>
            ))}
            <Switch
              size="md"
              label="phoneTouch"
              phoneTouch
              checked={toggles.on}
              onCheckedChange={(checked) =>
                setToggles({ ...toggles, on: checked })
              }
            />
          </div>
        </div>
      </Section>

      <Section
        id="segmented"
        title="SegmentedControl"
        note="Two sizes. Options can be `disabled`, carry a `swatch` chip, or take a chosen `style` colour — the one place a segment accepts a runtime colour."
      >
        <div {...stylex.props(s.rowsWrap)}>
          <div {...stylex.props(s.rowWide)}>
            <SegmentedControl
              aria-label="Size"
              size="md"
              value={segment}
              onValueChange={setSegment}
              options={[
                { value: "sm", label: "sm" },
                { value: "md", label: "md" },
                { value: "lg", label: "lg", disabled: true },
              ]}
            />
            <SegmentedControl
              aria-label="Size"
              size="sm"
              value={segment}
              onValueChange={setSegment}
              options={[
                { value: "sm", label: "sm" },
                { value: "md", label: "md" },
                { value: "lg", label: "lg", disabled: true },
              ]}
            />
          </div>
          <div {...stylex.props(s.rowWide)}>
            <SegmentedControl
              aria-label="Annotation colour"
              value="amber"
              onValueChange={() => {}}
              options={[
                { value: "amber", label: "Amber", swatch: "#f59e0b" },
                { value: "violet", label: "Violet", swatch: "#8b5cf6" },
              ]}
            />
            <SegmentedControl
              aria-label="Chosen colour"
              value="mine"
              onValueChange={() => {}}
              options={[
                {
                  value: "mine",
                  label: colour,
                  style: { backgroundColor: colour, color: "#fff" },
                },
                { value: "default", label: "Layer default" },
              ]}
            />
          </div>
          <div {...stylex.props(s.rowWide)}>
            <SegmentedControl
              aria-label="Disabled group"
              value="sm"
              onValueChange={() => {}}
              disabled
              options={[
                { value: "sm", label: "sm" },
                { value: "md", label: "md" },
              ]}
            />
          </div>
        </div>
      </Section>

      <Section
        id="sliders"
        title="Slider"
        note="Two sizes. Below 1 the value prints with decimals; pass `format` to override."
      >
        <div {...stylex.props(s.cols)}>
          <Slider
            label="Opacity"
            value={opacity}
            min={0}
            max={1}
            step={0.01}
            onValueChange={setOpacity}
          />
          <Slider
            label="Retries"
            value={count}
            min={0}
            max={10}
            step={1}
            onValueChange={setCount}
          />
          <Slider
            label="size: dense"
            size="dense"
            value={opacity}
            min={0}
            max={1}
            step={0.01}
            onValueChange={setOpacity}
          />
          <Slider
            label="Custom format"
            value={count}
            min={0}
            max={10}
            step={1}
            format={(value) => `${value}×`}
            onValueChange={setCount}
          />
          <Slider
            label="Disabled"
            value={opacity}
            min={0}
            max={1}
            step={0.01}
            disabled
            onValueChange={setOpacity}
          />
        </div>
      </Section>

      <Section
        id="colour"
        title="ColorWell · ColorField"
        note="A bare well needs its `label` for an accessible name; `ColorField` adds the label row and an `aside`. `block` defaults to true despite the docstring offering a small square for a toolbar, so the square is the case that has to opt out — both shown per size."
      >
        <div {...stylex.props(s.cols)}>
          {CONTROL_SIZES.map((size) => (
            <div key={size} {...stylex.props(s.row)}>
              <ColorWell
                size={size}
                label={`Well ${size}`}
                block={false}
                value={colour}
                onChange={setColour}
              />
              <ColorWell
                size={size}
                label="disabled square"
                block={false}
                value="#94a3b8"
                disabled
                onChange={() => {}}
              />
              <span {...stylex.props(s.axisWide)}>{size}</span>
            </div>
          ))}
          <ColorField
            label="Line colour"
            aside={colour}
            value={colour}
            onChange={setColour}
          />
          <ColorWell
            size="md"
            label="block — a styled layer"
            block
            value="#0ea5e9"
            onChange={() => {}}
          />
        </div>
      </Section>

      <Section
        id="notices"
        title="Notice"
        note="Three tones, two variants. `banner` is the full-width strip a panel's top edge takes; `action` and `onDismiss` are optional."
      >
        <div {...stylex.props(s.stack)}>
          {NOTICE_TONES.map((tone) => (
            <Notice
              key={tone}
              tone={tone}
              action={
                <Button size="xs" variant="secondary">
                  <RefreshCw size={12} />
                  Retry
                </Button>
              }
            >
              <strong>{tone}</strong> · inline — the run failed: connection
              refused.
            </Notice>
          ))}
          {NOTICE_TONES.map((tone) => (
            <Notice key={tone} tone={tone} variant="banner">
              <strong>{tone}</strong> · banner — a workspace-wide strip.
            </Notice>
          ))}
          {noticeOpen ? (
            <Notice
              tone="warning"
              onDismiss={() => setNoticeOpen(false)}
              dismissLabel="Dismiss"
            >
              Dismissible — pressing Dismiss removes this notice.
            </Notice>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setNoticeOpen(true)}
            >
              Restore the dismissed notice
            </Button>
          )}
        </div>
      </Section>

      <Section
        id="surfaces"
        title="Surface"
        note="Three tones × four shapes. `sunken` is what a card's body takes; `floating` is what a portal paints."
      >
        {SURFACE_TONES.map((tone) => (
          <div key={tone} {...stylex.props(s.surfaces)}>
            {SURFACE_SHAPES.map((shape) => (
              <Surface
                key={shape}
                tone={tone}
                shape={shape}
                padding="md"
                {...stylex.props(s.surfaceCell)}
              >
                {tone} · {shape}
              </Surface>
            ))}
          </div>
        ))}
      </Section>

      <Section
        id="menus"
        title="Menu"
        note="Items take `icon`, `hint`, `danger`, `active`. Groups, radio groups, checkbox items and separators are all live here."
      >
        <Menu>
          <MenuTrigger render={<Button size="sm" variant="secondary" />}>
            <span {...stylex.props(s.menuTrigger)}>
              <MoreHorizontal size={13} />
              Open the menu
            </span>
          </MenuTrigger>
          <MenuContent side="bottom" align="start" sideOffset={6}>
            <MenuGroup>
              <MenuGroupLabel>Graph</MenuGroupLabel>
              <MenuItem icon={<Plus size={13} />} hint="⌘N">
                Add node
              </MenuItem>
              <MenuItem active icon={<Settings2 size={13} />} hint="open">
                Node settings
              </MenuItem>
              <MenuItem disabled hint="no selection">
                Paste
              </MenuItem>
            </MenuGroup>
            <MenuSeparator />
            <MenuGroup>
              <MenuGroupLabel>Show</MenuGroupLabel>
              <MenuCheckboxItem
                checked={menuFlags.grid}
                onCheckedChange={(checked) =>
                  setMenuFlags({ ...menuFlags, grid: checked })
                }
              >
                Grid
              </MenuCheckboxItem>
              <MenuCheckboxItem
                checked={menuFlags.guides}
                onCheckedChange={(checked) =>
                  setMenuFlags({ ...menuFlags, guides: checked })
                }
              >
                Snap guides
              </MenuCheckboxItem>
            </MenuGroup>
            <MenuSeparator />
            <MenuRadioGroup value={menuChoice} onValueChange={setMenuChoice}>
              <MenuGroupLabel>Behaviour</MenuGroupLabel>
              <MenuRadioItem value="snap">Snap to grid</MenuRadioItem>
              <MenuRadioItem value="free">Free placement</MenuRadioItem>
            </MenuRadioGroup>
            <MenuSeparator />
            <MenuItem danger icon={<Trash2 size={13} />} hint="⌫">
              Delete selection
            </MenuItem>
          </MenuContent>
        </Menu>
      </Section>

      <Section
        id="dialogs"
        title="Dialog"
        note="Six widths: compact 430px, default 640px, form 520px, wide min(960px, 94vw), catalog min(1040px, 100vw−24px), viewport min(1340px, 100vw−28px). Below 620px every one of them goes full-bleed. Actions come from the call site, not the kit, so they can read right in both locales."
      >
        <div {...stylex.props(s.row)}>
          {DIALOG_SIZES.map((size) => (
            <Button
              key={size}
              size="sm"
              variant="secondary"
              onClick={() => setDialog(size)}
            >
              size=&#34;{size}&#34;
            </Button>
          ))}
        </div>
        <Dialog
          open={dialog !== null}
          onOpenChange={(open) => !open && setDialog(null)}
        >
          <DialogContent size={dialog ?? "default"}>
            <DialogHeader>
              <DialogTitle>Dialog · size=&#34;{dialog}&#34;</DialogTitle>
              <DialogDescription>
                The body scrolls when the content outgrows the frame, which is
                what keeps a long form inside a short landscape window.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <div {...stylex.props(s.stack)}>
                <Field label="Name" description="Shown in the node picker.">
                  <TextInput defaultValue="Team gateway" />
                </Field>
                <Field
                  label="Key"
                  error="The provider returned 401 for that key."
                >
                  <TextInput type="password" placeholder="Paste key" />
                </Field>
                <Notice tone="neutral">
                  A notice sits in a dialog body the same way it sits in a
                  panel.
                </Notice>
                <Checkbox
                  label="Make it the default for new nodes"
                  checked={checks.on}
                  onCheckedChange={(checked) =>
                    setChecks({ ...checks, on: checked })
                  }
                />
              </div>
            </DialogBody>
            <div {...stylex.props(s.actions)}>
              <Button size="md" variant="ghost" onClick={() => setDialog(null)}>
                Cancel
              </Button>
              <Button size="md" variant="primary">
                <KeyRound size={14} />
                Save key
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </Section>
    </div>
  );
}

function Section({
  id,
  title,
  note,
  children,
}: {
  id: string;
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} {...stylex.props(s.section)}>
      <div {...stylex.props(s.sectionHead)}>
        <h2 {...stylex.props(s.heading)}>{title}</h2>
        <p {...stylex.props(s.note)}>{note}</p>
      </div>
      {children}
    </section>
  );
}

function FragmentRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <span {...stylex.props(s.axis)}>{label}</span>
      {children}
    </>
  );
}

const s = stylex.create({
  page: {
    boxSizing: "border-box",
    display: "flex",
    flexDirection: "column",
    gap: "28px",
    minHeight: "100%",
    padding: "16px 16px 48px",
    width: "100%",
  },
  nav: {
    display: "flex",
    flexWrap: "wrap",
    gap: "4px 12px",
    position: "sticky",
    top: "-16px",
    background: "var(--background)",
    paddingTop: "16px",
    paddingBottom: "10px",
    borderBottom: "1px solid var(--border)",
    zIndex: 1,
  },
  navLink: {
    color: "var(--muted-foreground)",
    fontSize: "11px",
    textDecoration: "none",
  },
  section: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  sectionHead: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  heading: {
    fontSize: "15px",
    fontWeight: 600,
    letterSpacing: "-0.01em",
    margin: 0,
  },
  note: {
    color: "var(--muted-foreground)",
    fontSize: "11.5px",
    lineHeight: 1.5,
    margin: 0,
    maxWidth: "84ch",
  },
  axisWide: {
    color: "var(--muted-foreground)",
    fontSize: "10px",
  },
  natural: {
    justifySelf: "start",
  },
  axis: {
    color: "var(--muted-foreground)",
    fontSize: "10px",
    fontVariantNumeric: "tabular-nums",
    paddingTop: "6px",
  },
  matrix: {
    alignItems: "start",
    columnGap: "10px",
    display: "grid",
    gridTemplateColumns: "58px repeat(7, minmax(0, auto))",
    // Seven variants do not fit a phone. The matrix scrolls sideways rather
    // than pushing the whole page wider, which would drag every other section
    // with it.
    overflowX: "auto",
    paddingBottom: "6px",
    rowGap: "10px",
  },
  matrixIcons: {
    alignItems: "center",
    columnGap: "10px",
    display: "grid",
    gridTemplateColumns: "58px repeat(5, minmax(0, 96px))",
    justifyContent: "start",
    overflowX: "auto",
    paddingBottom: "6px",
    rowGap: "10px",
  },
  row: {
    alignItems: "center",
    display: "flex",
    flexWrap: "wrap",
    gap: "10px",
  },
  rowWide: {
    alignItems: "center",
    display: "flex",
    flex: "1 1 320px",
    gap: "10px",
    maxWidth: "420px",
    minWidth: "0",
  },
  rowsWrap: {
    alignItems: "center",
    display: "flex",
    flexWrap: "wrap",
    gap: "10px",
  },
  stack: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  },
  cols: {
    display: "grid",
    gap: "14px",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    alignItems: "start",
  },
  half: {
    maxWidth: "320px",
  },
  aside: {
    color: "var(--muted-foreground)",
    fontSize: "10px",
  },
  surfaces: {
    display: "grid",
    gap: "10px",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  },
  surfaceCell: {
    color: "var(--muted-foreground)",
    fontSize: "11px",
    minHeight: "44px",
  },
  menuTrigger: {
    alignItems: "center",
    display: "flex",
    gap: "6px",
  },
  actions: {
    display: "flex",
    gap: "8px",
    justifyContent: "flex-end",
    paddingTop: "12px",
  },
});
