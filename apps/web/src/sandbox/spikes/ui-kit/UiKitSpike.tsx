import { Fragment, useState } from "react";

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
import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * The kit in one place: every `src/components/ui` part at every size it declares,
 * in the states a call site actually reaches, and — above the matrices — three
 * context frames showing what those sizes cost inside the 300px canvas card, the
 * 360px side panel and the 520px form a control really has to fit.
 *
 * Pixel numbers are printed next to the control they measure. A size means
 * nothing on its own: `dense` and `sm` are 3px apart and only the row they live
 * in says which one is right.
 *
 * The size lists below are written out rather than derived from the types, so
 * adding a variant to the kit leaves this lab visibly incomplete instead of
 * silently skipping it.
 *
 * `NOTES.md` beside this file holds the call-site counts behind each option and
 * the shape the next cut should take. Read it before changing the layout here.
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

/** The glyph that fits each `IconButton` box; the kit does not size the icon. */
const ICON_GLYPH_SIZE: Record<(typeof ICON_SIZES)[number], number> = {
  "2xs": 11,
  xs: 12,
  sm: 14,
  md: 15,
  lg: 16,
};

const BUTTON_SIZE_PX: Record<(typeof BUTTON_SIZES)[number], string> = {
  xs: "22px",
  sm: "28px",
  md: "32px",
  lg: "36px",
  text: "auto",
};

const ICON_SIZE_PX: Record<(typeof ICON_SIZES)[number], string> = {
  "2xs": "20px",
  xs: "22px",
  sm: "26px",
  md: "28px",
  lg: "32px",
};

const CONTROL_SIZE_PX: Record<(typeof CONTROL_SIZES)[number], string> = {
  md: "32px",
  sm: "28px",
  dense: "25px",
};

const SECTIONS = [
  { id: "contexts", label: "In context" },
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
  { id: "unused", label: "Unused" },
] as const;

type DialogSize = (typeof DIALOG_SIZES)[number];

export function UiKitSpike() {
  const [pressed, setPressed] = useState(true);
  const [toggles, setToggles] = useState({ on: true, off: false });
  const [checks, setChecks] = useState({ on: true, off: false });
  const [segment, setSegment] = useState("md");
  const [cardSegment, setCardSegment] = useState("nodes");
  const [panelSegment, setPanelSegment] = useState("layers");
  const [opacity, setOpacity] = useState(0.42);
  const [count, setCount] = useState(6);
  const [colour, setColour] = useState("#8b5cf6");
  const [noticeOpen, setNoticeOpen] = useState(true);
  const [menuFlags, setMenuFlags] = useState({ grid: true, guides: false });
  const [menuChoice, setMenuChoice] = useState("snap");
  const [dialog, setDialog] = useState<DialogSize | null>(null);
  const [formDialogOpen, setFormDialogOpen] = useState(false);

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
        id="contexts"
        title="In context"
        note="Three targets the kit has to serve: a 300px canvas card at 9px type, a 360px side panel at 12px, and a 520px form. Everything below is the same kit out of context; a size only means anything against one of these."
      >
        <div {...stylex.props(s.frames)}>
          <CanvasCardFrame
            segment={cardSegment}
            onSegmentChange={setCardSegment}
            colour={colour}
            onColourChange={setColour}
          />
          <SidePanelFrame
            segment={panelSegment}
            onSegmentChange={setPanelSegment}
            checked={checks.on}
            onCheckedChange={(checked) => setChecks({ ...checks, on: checked })}
          />
          <FormDialogFrame />
        </div>
      </Section>

      <Section
        id="buttons"
        title="Button"
        note="7 variants × 5 sizes. `text` has no box — its height comes from the line it sits on; `plain` keeps the box but borrows the surrounding weight. Heights are printed beside each size."
      >
        <div {...stylex.props(s.matrix)}>
          <span />
          {BUTTON_VARIANTS.map((variant) => (
            <span key={variant} {...stylex.props(s.axis)}>
              {variant}
            </span>
          ))}
          {BUTTON_SIZES.map((size) => (
            <FragmentRow key={size} label={`${size} ${BUTTON_SIZE_PX[size]}`}>
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
          <span {...stylex.props(s.axisWide)}>default</span>
          <Button variant="secondary" size="sm">
            secondary
          </Button>
          <Button variant="soft" size="sm">
            soft
          </Button>
          <Button variant="ghost" size="sm">
            ghost
          </Button>
          <Button variant="secondary" size="sm" swatch={colour}>
            swatch
          </Button>
        </div>
        <div {...stylex.props(s.row)}>
          <span {...stylex.props(s.axisWide)}>pressed</span>
          <Button
            variant="secondary"
            size="sm"
            pressed={pressed}
            onClick={() => setPressed((value) => !value)}
          >
            secondary: {String(pressed)}
          </Button>
          <Button variant="soft" size="sm" pressed>
            soft
          </Button>
          <Button variant="ghost" size="sm" pressed>
            ghost
          </Button>
        </div>
        <div {...stylex.props(s.row)}>
          <span {...stylex.props(s.axisWide)}>disabled</span>
          <Button variant="primary" size="sm" disabled>
            primary
          </Button>
          <Button variant="secondary" size="sm" disabled>
            secondary
          </Button>
          <Button variant="danger" size="sm" disabled>
            danger
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
        note="5 variants × 5 sizes. `label` is required: it is the accessible name and, by default, the tooltip. Pass `title={null}` where the control already sits in visible text and the button draws no tooltip — shown live in the states row. The kit does not size the glyph, so each box is paired with the icon size that fits it: 11 / 12 / 14 / 15 / 16."
      >
        <div {...stylex.props(s.matrixIcons)}>
          <span />
          {ICON_VARIANTS.map((variant) => (
            <span key={variant} {...stylex.props(s.axis)}>
              {variant}
            </span>
          ))}
          {ICON_SIZES.map((size) => (
            <FragmentRow key={size} label={`${size} ${ICON_SIZE_PX[size]}`}>
              {ICON_VARIANTS.map((variant) => (
                <IconButton
                  key={variant}
                  label={`${variant} ${size}`}
                  size={size}
                  variant={variant}
                >
                  <Settings2 size={ICON_GLYPH_SIZE[size]} />
                </IconButton>
              ))}
            </FragmentRow>
          ))}
        </div>
        <div {...stylex.props(s.row)}>
          <span {...stylex.props(s.axisWide)}>states</span>
          <IconButton
            label="No tooltip — title={null}"
            title={null}
            variant="ghost"
            size="sm"
          >
            <Settings2 size={14} />
          </IconButton>
          <IconButton label="pressed ghost" variant="ghost" size="sm" pressed>
            <Settings2 size={14} />
          </IconButton>
          <IconButton label="pressed soft" variant="soft" size="sm" pressed>
            <Settings2 size={14} />
          </IconButton>
          <IconButton label="pressed accent" variant="accent" size="sm" pressed>
            <Settings2 size={14} />
          </IconButton>
          <IconButton
            label="primary disabled"
            variant="primary"
            size="sm"
            disabled
          >
            <Settings2 size={14} />
          </IconButton>
          <IconButton label="ghost disabled" variant="ghost" size="sm" disabled>
            <Settings2 size={14} />
          </IconButton>
          <IconButton
            label="with a tooltip of its own"
            title="Hover me — the label is the tooltip by default"
            variant="ghost"
            size="sm"
          >
            <Settings2 size={14} />
          </IconButton>
        </div>
        <p {...stylex.props(s.note)}>
          Left to right: <code>title=&#34;&#123;null&#34;&#125;</code>, pressed
          ghost / soft / accent, primary disabled, ghost disabled, custom
          tooltip. <code>accent</code> keeps its tint when pressed and takes a
          ring instead of the grey wash, because on a dock one control is always
          tinted.
        </p>
      </Section>

      <Section
        id="links"
        title="ButtonLink"
        note="An anchor with Button's shape, for actions that navigate rather than act. Same 7 variants and 5 sizes; each row is its size."
      >
        <div {...stylex.props(s.matrix)}>
          <span />
          {BUTTON_VARIANTS.map((variant) => (
            <span key={variant} {...stylex.props(s.axis)}>
              {variant}
            </span>
          ))}
          {BUTTON_SIZES.map((size) => (
            <FragmentRow key={size} label={`${size} ${BUTTON_SIZE_PX[size]}`}>
              {BUTTON_VARIANTS.map((variant) => (
                <ButtonLink
                  key={variant}
                  href="#links"
                  size={size}
                  variant={variant}
                  xstyle={s.natural}
                >
                  {variant}
                </ButtonLink>
              ))}
            </FragmentRow>
          ))}
        </div>
      </Section>

      <Section
        id="fields"
        title="Field · TextInput · TextArea"
        note="Two steps: `md` (32px) and `dense` (25px, 9px type). `error` replaces `description`, marks the field's control `aria-invalid` and paints the red ring on both the input and the textarea; `aside` sits at the right of the label row."
      >
        <div {...stylex.props(s.cols)}>
          <Field
            label="Base URL · valid"
            description="Any OpenAI-compatible endpoint."
          >
            <TextInput defaultValue="https://api.openai.com/v1" mono />
          </Field>
          <Field
            label="API key · error"
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
          <Field label="size: dense · 25px" size="dense">
            <TextInput defaultValue="the canvas-card step" />
          </Field>
          <Field
            label="Prompt · error on a textarea"
            error="Keep the system prompt under 2 000 characters."
          >
            <TextArea
              rows={3}
              defaultValue="a prompt long enough to fail validation"
            />
          </Field>
          <Field label="System prompt · dense" size="dense">
            <TextArea rows={2} defaultValue="dense rows are 25px too" />
          </Field>
          <Field label="Schema" description="A JSON Schema document.">
            <TextArea rows={3} mono defaultValue={'{\n  "type": "object"\n}'} />
          </Field>
        </div>
      </Section>

      <Section
        id="selects"
        title="Select"
        note="Three sizes: md 32px, sm 28px, dense 25px."
      >
        <div {...stylex.props(s.cols)}>
          {CONTROL_SIZES.map((size) => (
            <Field
              key={size}
              label={`size: ${size} · ${CONTROL_SIZE_PX[size]}`}
            >
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
        note="Both take three sizes and a `label` that toggles them, so a row needs no other markup. `phoneTouch` is in the regression section below — never on a control inside a card."
      >
        <div {...stylex.props(s.cols)}>
          <div {...stylex.props(s.stack)}>
            {CONTROL_SIZES.map((size) => (
              <div key={size} {...stylex.props(s.row)}>
                <span {...stylex.props(s.axisWide)}>
                  {size} · {CONTROL_SIZE_PX[size]}
                </span>
                <Checkbox
                  size={size}
                  label="on"
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
          </div>
          <div {...stylex.props(s.stack)}>
            {CONTROL_SIZES.map((size) => (
              <div key={size} {...stylex.props(s.row)}>
                <span {...stylex.props(s.axisWide)}>
                  {size} · {CONTROL_SIZE_PX[size]}
                </span>
                <Switch
                  size={size}
                  label="on"
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
          </div>
        </div>
      </Section>

      <Section
        id="segmented"
        title="SegmentedControl"
        note="Three wells: md 32px, sm 28px, dense 25px (a 21px segment plus 2px of padding). Options can be `disabled`, carry a `swatch` chip, or take a chosen `style` colour — the one place a segment accepts a runtime colour."
      >
        <div {...stylex.props(s.rowsWrap)}>
          {CONTROL_SIZES.map((size) => (
            <div key={size} {...stylex.props(s.rowWide)}>
              <SegmentedControl
                aria-label={`Segmented size ${size}`}
                size={size}
                value={segment}
                onValueChange={setSegment}
                options={[
                  { value: "sm", label: "sm" },
                  { value: "md", label: "md" },
                  { value: "lg", label: "lg", disabled: true },
                ]}
              />
              <span {...stylex.props(s.axisWide)}>
                {size} · {CONTROL_SIZE_PX[size]} well
              </span>
            </div>
          ))}
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
            <span {...stylex.props(s.axisWide)}>swatch</span>
          </div>
          <div {...stylex.props(s.rowWide)}>
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
            <span {...stylex.props(s.axisWide)}>custom style</span>
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
            <span {...stylex.props(s.axisWide)}>disabled group</span>
          </div>
        </div>
      </Section>

      <Section
        id="sliders"
        title="Slider"
        note="Two sizes: md (14px thumb) and dense (10px thumb, 9px label). Below 1 the value prints with decimals; pass `format` to override. A disabled slider dims its label, its value and its fill."
      >
        <div {...stylex.props(s.cols)}>
          <Slider
            label="Opacity · md · decimal"
            value={opacity}
            min={0}
            max={1}
            step={0.01}
            onValueChange={setOpacity}
          />
          <Slider
            label="Retries · md · integer"
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
        note="`block` defaults to true: the well fills the row, which is a styled layer. Pass `block={false}` for the toolbar square, which matches its size exactly — dense 25×25, sm 28×28, md 32×32. A bare well needs its `label` for an accessible name; `ColorField` adds the label row and an `aside`."
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
                label={`disabled ${size}`}
                block={false}
                value="#94a3b8"
                disabled
                onChange={() => {}}
              />
              <span {...stylex.props(s.axisWide)}>
                {size} · {CONTROL_SIZE_PX[size]} square
              </span>
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
            label="block (the default) — a styled layer"
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
        note="Three tones × four shapes. `sunken` is what a card's body takes and what a borderless control sits on, so a `soft` button is drawn inside every cell — if it disappears, the tone has stopped separating."
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
                <span {...stylex.props(s.surfaceLabel)}>
                  {tone} · {shape}
                </span>
                <Button variant="soft" size="xs">
                  soft on {tone}
                </Button>
              </Surface>
            ))}
          </div>
        ))}
      </Section>

      <Section
        id="menus"
        title="Menu"
        note="Items take `icon`, `hint`, `danger`, `active`. Groups, radio groups, checkbox items and separators are all live here. The trigger sits in a plain flex row: `Menu` renders its trigger inline, and a stretch parent would pull a `secondary` trigger to full width."
      >
        <div {...stylex.props(s.row)}>
          <Menu>
            <div {...stylex.props(s.row)}>
              <MenuTrigger render={<Button size="sm" variant="secondary" />}>
                <span {...stylex.props(s.menuTrigger)}>
                  <MoreHorizontal size={13} />
                  Open the menu
                </span>
              </MenuTrigger>
            </div>
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
        </div>
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

      <Section
        id="unused"
        title="Unused & regression guards"
        note="Options with few or no call sites that stay visible on purpose: each one is a fix that would otherwise regress silently. `phoneTouch` is the 44px phone target; `IconButton variant=&#34;primary&#34;` has never been rendered; `plain`, `dashed` and `size=&#34;text&#34;` are 10 of 114 button choices."
      >
        <div {...stylex.props(s.cols)}>
          <div {...stylex.props(s.stack)}>
            <span {...stylex.props(s.axisWide)}>
              Switch phoneTouch — 44px row and a 20px centred thumb below 620px;
              both states, because the desktop <code>translateX</code> and the
              phone shift are separate recipes
            </span>
            <Switch
              size="md"
              label="phoneTouch · on"
              phoneTouch
              checked={toggles.on}
              onCheckedChange={(checked) =>
                setToggles({ ...toggles, on: checked })
              }
            />
            <Switch
              size="md"
              label="phoneTouch · off"
              phoneTouch
              checked={toggles.off}
              onCheckedChange={(checked) =>
                setToggles({ ...toggles, off: checked })
              }
            />
            <Switch
              size="sm"
              label="phoneTouch · sm · on"
              phoneTouch
              checked={toggles.on}
              onCheckedChange={(checked) =>
                setToggles({ ...toggles, on: checked })
              }
            />
            <Switch
              size="dense"
              label="phoneTouch · dense · off"
              phoneTouch
              checked={toggles.off}
              onCheckedChange={(checked) =>
                setToggles({ ...toggles, off: checked })
              }
            />
          </div>
          <div {...stylex.props(s.stack)}>
            <span {...stylex.props(s.axisWide)}>
              Checkbox phoneTouch — the row grows to 44px; the box does not
            </span>
            <Checkbox
              size="md"
              label="phoneTouch · checked"
              phoneTouch
              checked={checks.on}
              onCheckedChange={(checked) =>
                setChecks({ ...checks, on: checked })
              }
            />
            <Checkbox
              size="md"
              label="phoneTouch · off"
              phoneTouch
              checked={checks.off}
              onCheckedChange={(checked) =>
                setChecks({ ...checks, off: checked })
              }
            />
          </div>
          <div {...stylex.props(s.stack)}>
            <span {...stylex.props(s.axisWide)}>
              IconButton variant=&#34;primary&#34; — 0 call sites
            </span>
            <div {...stylex.props(s.row)}>
              <IconButton label="primary" variant="primary" size="md">
                <Settings2 size={15} />
              </IconButton>
              <IconButton
                label="primary pressed"
                variant="primary"
                size="md"
                pressed
              >
                <Settings2 size={15} />
              </IconButton>
              <IconButton
                label="primary disabled"
                variant="primary"
                size="md"
                disabled
              >
                <Settings2 size={15} />
              </IconButton>
              <IconButton
                label="primary round"
                variant="primary"
                size="md"
                shape="round"
              >
                <Settings2 size={15} />
              </IconButton>
            </div>
          </div>
          <div {...stylex.props(s.stack)}>
            <span {...stylex.props(s.axisWide)}>
              Low-usage Button and ButtonLink
            </span>
            <div {...stylex.props(s.row)}>
              {BUTTON_SIZES.map((size) => (
                <Button key={size} variant="plain" size={size}>
                  plain {size}
                </Button>
              ))}
            </div>
            <div {...stylex.props(s.row)}>
              {BUTTON_SIZES.map((size) => (
                <Button key={size} variant="dashed" size={size}>
                  dashed {size}
                </Button>
              ))}
            </div>
            <div {...stylex.props(s.row)}>
              <Button variant="secondary" size="text">
                size=&#34;text&#34; sits on the line
              </Button>
              <ButtonLink href="#unused" size="xs" variant="ghost">
                ButtonLink xs
              </ButtonLink>
              <ButtonLink href="#unused" size="sm" variant="secondary">
                ButtonLink sm
              </ButtonLink>
            </div>
          </div>
          <div {...stylex.props(s.stack)}>
            <span {...stylex.props(s.axisWide)}>
              DialogContent size=&#34;form&#34; — 520px, the frame the panel
              above imitates
            </span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setFormDialogOpen(true)}
            >
              Open size=&#34;form&#34;
            </Button>
          </div>
        </div>
        <Dialog open={formDialogOpen} onOpenChange={setFormDialogOpen}>
          <DialogContent size="form">
            <DialogHeader>
              <DialogTitle>Form dialog</DialogTitle>
              <DialogDescription>
                The same geometry as the 520px frame at the top of the page,
                with the real overlay, scroll and focus handling.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <div {...stylex.props(s.stack)}>
                <Field label="Name">
                  <TextInput defaultValue="Team gateway" />
                </Field>
                <Field
                  label="Key"
                  error="The provider returned 401 for that key."
                >
                  <TextInput type="password" placeholder="Paste key" />
                </Field>
              </div>
            </DialogBody>
            <div {...stylex.props(s.actions)}>
              <Button
                size="md"
                variant="ghost"
                onClick={() => setFormDialogOpen(false)}
              >
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

      <p {...stylex.props(s.note)}>
        Call-site counts and the plan for the next cut:{" "}
        <code>src/sandbox/spikes/ui-kit/NOTES.md</code>, refreshed with{" "}
        <code>bun apps/web/src/sandbox/spikes/ui-kit/usage.mjs</code>.
      </p>
    </div>
  );
}

/** A canvas card: 300px wide, 25px rows, 9px type. Every control is `dense`. */
function CanvasCardFrame({
  segment,
  onSegmentChange,
  colour,
  onColourChange,
}: {
  segment: string;
  onSegmentChange: (value: string) => void;
  colour: string;
  onColourChange: (value: string) => void;
}) {
  const [opacity, setOpacity] = useState(0.42);
  const [labelOn, setLabelOn] = useState(true);
  const [guides, setGuides] = useState(false);
  return (
    <Surface
      tone="sunken"
      shape="lg"
      padding="none"
      xstyle={[s.frame, s.frameCard]}
    >
      <div {...stylex.props(s.frameHead)}>
        <span {...stylex.props(s.frameTitle)}>Canvas card</span>
        <span {...stylex.props(s.frameSpec)}>
          300px · dense · 25px rows · 9px type
        </span>
      </div>
      <div {...stylex.props(s.frameBody)}>
        <div {...stylex.props(s.frameRow)}>
          <span {...stylex.props(s.cardTitle)}>Vector layer</span>
          <IconButton label="Card settings" size="2xs" variant="ghost">
            <Settings2 size={11} />
          </IconButton>
          <SegmentedControl
            aria-label="Card view"
            size="dense"
            value={segment}
            onValueChange={onSegmentChange}
            options={[
              { value: "nodes", label: "Nodes" },
              { value: "edges", label: "Edges" },
              { value: "code", label: "Code" },
            ]}
          />
        </div>
        <Field label="Name" size="dense">
          <TextInput defaultValue="Base map" />
        </Field>
        <Field label="Source" size="dense">
          <Select defaultValue="osm">
            <option value="osm">OpenStreetMap tiles</option>
            <option value="local">Local GeoJSON</option>
          </Select>
        </Field>
        <Slider
          label="Opacity"
          size="dense"
          value={opacity}
          min={0}
          max={1}
          step={0.01}
          onValueChange={setOpacity}
        />
        <ColorField
          label="Stroke"
          aside={colour}
          size="dense"
          value={colour}
          onChange={onColourChange}
        />
        <div {...stylex.props(s.frameRow)}>
          <Switch
            size="dense"
            label="Labels"
            checked={labelOn}
            onCheckedChange={setLabelOn}
          />
          <Checkbox
            size="dense"
            label="Guides"
            checked={guides}
            onCheckedChange={setGuides}
          />
        </div>
        <div {...stylex.props(s.frameRow)}>
          <Button size="xs" variant="secondary">
            <Plus size={11} />
            Add style
          </Button>
        </div>
      </div>
      <div {...stylex.props(s.frameFoot)}>
        300px · 25px rows · 20px icon · 22px btn
      </div>
    </Surface>
  );
}

/** A side panel: 360px wide, `sm` controls, 12px type. */
function SidePanelFrame({
  segment,
  onSegmentChange,
  checked,
  onCheckedChange,
}: {
  segment: string;
  onSegmentChange: (value: string) => void;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <Surface
      tone="raised"
      shape="md"
      padding="none"
      xstyle={[s.frame, s.framePanel]}
    >
      <div {...stylex.props(s.frameHead)}>
        <span {...stylex.props(s.frameTitle)}>Side panel</span>
        <span {...stylex.props(s.frameSpec)}>360px · sm · 28px / 26px</span>
      </div>
      <div {...stylex.props(s.frameBody)}>
        <div {...stylex.props(s.frameRow)}>
          <span {...stylex.props(s.panelTitle)}>Layers</span>
          <IconButton label="Refresh layers" size="sm" variant="ghost">
            <RefreshCw size={14} />
          </IconButton>
        </div>
        <SegmentedControl
          aria-label="Panel view"
          size="sm"
          value={segment}
          onValueChange={onSegmentChange}
          options={[
            { value: "layers", label: "Layers" },
            { value: "objects", label: "Objects" },
            { value: "history", label: "History" },
          ]}
        />
        <Field label="Filter">
          <TextInput placeholder="Filter layers" />
        </Field>
        <Notice tone="neutral">Two layers are hidden in this view.</Notice>
        <Button variant="dashed" size="sm" block>
          <Plus size={12} />
          Add layer
        </Button>
        <div {...stylex.props(s.frameRow)}>
          <Checkbox
            size="sm"
            label="Snap to layer"
            checked={checked}
            onCheckedChange={onCheckedChange}
          />
        </div>
        <div {...stylex.props(s.actionsRow)}>
          <Button size="sm" variant="secondary">
            Reset
          </Button>
          <Button size="sm" variant="primary">
            Apply
          </Button>
        </div>
      </div>
      <div {...stylex.props(s.frameFoot)}>
        360px · 28px controls · 26px icon
      </div>
    </Surface>
  );
}

/** A form dialog at its 520px `size="form"` width, painted inline (real one below). */
function FormDialogFrame() {
  const [agree, setAgree] = useState(true);
  const [locked, setLocked] = useState(false);
  return (
    <Surface
      tone="floating"
      shape="lg"
      padding="none"
      xstyle={[s.frame, s.frameForm]}
    >
      <div {...stylex.props(s.frameHead)}>
        <span {...stylex.props(s.frameTitle)}>Form / dialog</span>
        <span {...stylex.props(s.frameSpec)}>
          520px · size=&#34;form&#34; · md · 32px
        </span>
      </div>
      <div {...stylex.props(s.frameBody)}>
        <div {...stylex.props(s.stack)}>
          <span {...stylex.props(s.panelTitle)}>New provider key</span>
          <span {...stylex.props(s.frameDesc)}>
            A name and a secret. The invalid row shows the ring a server error
            paints.
          </span>
        </div>
        <Field label="Name" description="Shown in the node picker.">
          <TextInput defaultValue="Team gateway" />
        </Field>
        <Field label="Key" error="The provider returned 401 for that key.">
          <TextInput type="password" placeholder="Paste key" />
        </Field>
        <Field label="Scope">
          <Select size="md" defaultValue="workspace">
            <option value="personal">Personal</option>
            <option value="workspace">Workspace</option>
          </Select>
        </Field>
        <div {...stylex.props(s.frameRow)}>
          <Checkbox
            size="md"
            label="Default for new nodes"
            checked={agree}
            onCheckedChange={setAgree}
          />
          <Switch
            size="md"
            label="Locked"
            checked={locked}
            onCheckedChange={setLocked}
          />
        </div>
        <Notice tone="warning">
          Rotating a key invalidates every run using it.
        </Notice>
        <div {...stylex.props(s.actionsRow)}>
          <Button size="md" variant="ghost">
            Cancel
          </Button>
          <Button size="md" variant="primary">
            <KeyRound size={14} />
            Save key
          </Button>
        </div>
      </div>
      <div {...stylex.props(s.frameFoot)}>520px · 32px controls</div>
    </Surface>
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
    <Fragment>
      <span {...stylex.props(s.axis)}>{label}</span>
      {children}
    </Fragment>
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
    // A transparent sticky nav lets the specimens scroll straight through the
    // links. The page's own ground plus a hairline is what separates them.
    backgroundColor: tokens.colorBg,
    paddingTop: "16px",
    paddingBottom: "10px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    zIndex: 1,
  },
  navLink: {
    color: tokens.colorMuted,
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
    color: tokens.colorTextEmphasis,
    fontSize: "15px",
    fontWeight: 600,
    letterSpacing: "-0.01em",
    margin: 0,
  },
  note: {
    color: tokens.colorMuted,
    fontSize: "11.5px",
    lineHeight: 1.5,
    margin: 0,
    maxWidth: "84ch",
  },
  axisWide: {
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  natural: {
    justifySelf: "start",
  },
  axis: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontVariantNumeric: "tabular-nums",
    paddingTop: "6px",
  },
  frames: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "start",
    gap: "16px",
  },
  frame: {
    // Each frame keeps its real target width, but never a width the viewport
    // cannot give it.
    maxWidth: "100%",
    minWidth: "0",
    overflow: "hidden",
  },
  frameCard: {
    width: "300px",
  },
  framePanel: {
    width: "360px",
  },
  frameForm: {
    width: "520px",
  },
  frameHead: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: "8px",
    flexWrap: "wrap",
    paddingHorizontal: "10px",
    paddingBlock: "7px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  frameTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: "11px",
    fontWeight: 600,
  },
  frameSpec: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontVariantNumeric: "tabular-nums",
  },
  frameBody: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    padding: "10px",
    minHeight: "0",
  },
  frameRow: {
    display: "flex",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "8px",
    minWidth: 0,
  },
  frameFoot: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontVariantNumeric: "tabular-nums",
    paddingHorizontal: "10px",
    paddingBlock: "6px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  frameDesc: {
    color: tokens.colorMuted,
    fontSize: "11px",
    lineHeight: 1.45,
  },
  cardTitle: {
    color: tokens.colorText,
    fontSize: "9px",
    fontWeight: 600,
    flex: "1 1 auto",
    minWidth: 0,
  },
  panelTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: "12px",
    fontWeight: 600,
    flex: "1 1 auto",
    minWidth: 0,
  },
  matrix: {
    alignItems: "start",
    columnGap: "8px",
    display: "grid",
    gridTemplateColumns: "52px repeat(7, max-content)",
    justifyContent: "start",
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
    gridTemplateColumns: "74px repeat(5, max-content)",
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
    gap: "10px",
    flex: "1 1 320px",
    maxWidth: "460px",
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
    minWidth: 0,
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
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  surfaces: {
    display: "grid",
    gap: "10px",
    gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  },
  surfaceCell: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    alignItems: "flex-start",
    minHeight: "64px",
  },
  surfaceLabel: {
    color: tokens.colorMuted,
    fontSize: "11px",
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
  actionsRow: {
    display: "flex",
    gap: "8px",
    justifyContent: "flex-end",
  },
});
