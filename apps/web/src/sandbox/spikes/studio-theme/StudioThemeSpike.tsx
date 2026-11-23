"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Check,
  ChevronRight,
  Folder,
  FolderOpen,
  KeyRound,
  Layers,
  Moon,
  MoreHorizontal,
  Play,
  Plus,
  Search,
  Settings2,
  SlidersHorizontal,
  Sun,
  Upload,
} from "lucide-react";
import Link from "next/link";

import { BrandIcon } from "@/components/brand";
import { useTheme } from "@/components/theme";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, TextInput } from "@/components/ui/field";
import {
  Menu,
  MenuContent,
  MenuItem,
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

import { previousMonochromeTheme, studioEmeraldTheme } from "./themes";

type ThemePreset = "previous" | "studio" | "emerald";

const THEME_BY_PRESET = {
  previous: previousMonochromeTheme,
  studio: null,
  emerald: studioEmeraldTheme,
} as const;

const PROJECTS = [
  {
    id: "mogilev",
    name: "Spis wołostiej 1886 — test OCR",
    collection: "Mohylewska gubernia",
    meta: "2 scans · Mistral & Reducto",
    updated: "12m ago",
    status: "done" as const,
    variant: "table" as const,
  },
  {
    id: "metryki",
    name: "Księga metrykalna par. św. Jana (1792)",
    collection: "Zespół archiwalny",
    meta: "14 scans · Transcription in progress",
    updated: "2h ago",
    status: "active" as const,
    variant: "script" as const,
  },
  {
    id: "mapa",
    name: "WIG 1:100 000 — pas 42 słup 31",
    collection: "Kartografia historyczna",
    meta: "1 GeoTIFF · 3 vector layers",
    updated: "Yesterday",
    status: "idle" as const,
    variant: "map" as const,
  },
] as const;

/**
 * Single-screen design workbench for iterating on grafY's visual language
 * outside the canvas. Every control below is a real `src/components/ui` part,
 * so tweaking `themes.ts` immediately shows how the outer shell, project list,
 * sources panel, and provider settings harmonize with the canvas cards.
 */
export function StudioThemeSpike() {
  const { resolved, setPreference } = useTheme();
  const [preset, setPreset] = React.useState<ThemePreset>("studio");
  const [projectView, setProjectView] = React.useState<"recent" | "all">(
    "recent",
  );
  const [panelTab, setPanelTab] = React.useState<"sources" | "results">(
    "sources",
  );
  const [provider, setProvider] = React.useState("mistral");
  const [ocrMode, setOcrMode] = React.useState("table");
  const [autoDeskew, setAutoDeskew] = React.useState(true);
  const [keepLayout, setKeepLayout] = React.useState(true);
  const [confidence, setConfidence] = React.useState(0.85);
  const [selectedFile, setSelectedFile] = React.useState("volost_p01.jpg");
  const [query, setQuery] = React.useState("");

  const activeTheme = THEME_BY_PRESET[preset];

  return (
    <div {...stylex.props(activeTheme, s.shell)}>
      {/* Sticky theme switcher bar for instant A/B comparison */}
      <header {...stylex.props(s.bar)}>
        <div {...stylex.props(s.barLeft)}>
          <Link href="/sandbox" {...stylex.props(s.barBack)}>
            Sandbox
          </Link>
          <span {...stylex.props(s.barSlash)}>/</span>
          <span {...stylex.props(s.barTitle)}>Studio theme workbench</span>
          <span {...stylex.props(s.barHint)}>
            Edit <code>spikes/studio-theme/themes.ts</code> to iterate live
          </span>
        </div>
        <div {...stylex.props(s.barRight)}>
          <SegmentedControl
            aria-label="Theme preset"
            size="sm"
            value={preset}
            onValueChange={setPreset}
            options={[
              { value: "previous", label: "Previous" },
              { value: "studio", label: "Studio (Default)" },
              { value: "emerald", label: "Studio (Emerald)" },
            ]}
          />
          <IconButton
            label={
              resolved === "dark"
                ? "Switch to light mode"
                : "Switch to dark mode"
            }
            variant="soft"
            size="md"
            onClick={() =>
              setPreference(resolved === "dark" ? "light" : "dark")
            }
          >
            {resolved === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          </IconButton>
        </div>
      </header>

      <main {...stylex.props(s.canvas)}>
        {/* 1. Floating project chrome (replaces heavy 200px DevOps sidebar on canvas routes) */}
        <section {...stylex.props(s.block)}>
          <div {...stylex.props(s.blockHead)}>
            <h2 {...stylex.props(s.blockTitle)}>1 · Project chrome</h2>
            <span {...stylex.props(s.blockNote)}>
              Floating white plates over the canvas mist — project title, save
              status and primary run live here instead of a permanent 200px
              sidebar.
            </span>
          </div>

          <div {...stylex.props(s.chromeStage)}>
            <div {...stylex.props(s.floatingPill)}>
              <BrandIcon size={20} alt="" />
              <span {...stylex.props(s.pillDivider)} />
              <button type="button" {...stylex.props(s.crumbButton)}>
                Mohylew 1886
              </button>
              <ChevronRight size={13} {...stylex.props(s.crumbChevron)} />
              <span {...stylex.props(s.projectTitle)}>
                Spis wołostiej — porównanie OCR
              </span>
              <span {...stylex.props(s.savedBadge)}>
                <Check size={11} />
                Saved
              </span>
            </div>

            <div {...stylex.props(s.floatingPill)}>
              <Button size="sm" variant="ghost" pressed>
                <Layers size={13} />
                Sources
              </Button>
              <Button size="sm" variant="ghost">
                <SlidersHorizontal size={13} />
                Compare
              </Button>
              <span {...stylex.props(s.pillDivider)} />
              <Button size="sm" variant="primary">
                <Play size={12} />
                Run OCR
              </Button>
            </div>
          </div>
        </section>

        {/* 2. Projects home slice — visual dossiers instead of "4 nodes · 3 edges" */}
        <section {...stylex.props(s.block)}>
          <div {...stylex.props(s.blockHead)}>
            <h2 {...stylex.props(s.blockTitle)}>2 · Projects list</h2>
            <span {...stylex.props(s.blockNote)}>
              Scan thumbnails and research context replace raw node/edge counts.
            </span>
          </div>

          <div {...stylex.props(s.plate)}>
            <div {...stylex.props(s.plateToolbar)}>
              <div {...stylex.props(s.plateHeadingGroup)}>
                <h3 {...stylex.props(s.plateHeading)}>Projects</h3>
                <span {...stylex.props(s.countPill)}>3</span>
              </div>
              <div {...stylex.props(s.plateActions)}>
                <div {...stylex.props(s.searchWrap)}>
                  <Search size={13} {...stylex.props(s.searchIcon)} />
                  <TextInput
                    aria-label="Filter projects"
                    placeholder="Filter projects…"
                    value={query}
                    onChange={(event) => setQuery(event.currentTarget.value)}
                    xstyle={s.searchInput}
                  />
                </div>
                <SegmentedControl
                  aria-label="Project scope"
                  size="sm"
                  value={projectView}
                  onValueChange={setProjectView}
                  options={[
                    { value: "recent", label: "Recent" },
                    { value: "all", label: "All" },
                  ]}
                />
                <Button size="sm" variant="primary">
                  <Plus size={13} />
                  New project
                </Button>
              </div>
            </div>

            <div {...stylex.props(s.projectGrid)}>
              {PROJECTS.filter(
                (item) =>
                  !query.trim() ||
                  item.name.toLowerCase().includes(query.trim().toLowerCase()),
              ).map((project) => (
                <article key={project.id} {...stylex.props(s.projectCard)}>
                  <div {...stylex.props(s.thumbFrame)}>
                    <ArchivalThumb variant={project.variant} />
                  </div>
                  <div {...stylex.props(s.projectCardBody)}>
                    <div {...stylex.props(s.projectCardTop)}>
                      <span {...stylex.props(s.projectCardName)}>
                        {project.name}
                      </span>
                      <Menu>
                        <MenuTrigger
                          render={
                            <IconButton
                              label={`Actions for ${project.name}`}
                              size="xs"
                              variant="ghost"
                            />
                          }
                        >
                          <MoreHorizontal size={13} />
                        </MenuTrigger>
                        <MenuContent align="end" sideOffset={4}>
                          <MenuItem>Open project</MenuItem>
                          <MenuItem>Duplicate</MenuItem>
                          <MenuItem>Rename</MenuItem>
                          <MenuSeparator />
                          <MenuItem danger>Delete</MenuItem>
                        </MenuContent>
                      </Menu>
                    </div>
                    <span {...stylex.props(s.projectCardMeta)}>
                      {project.collection}
                    </span>
                    <div {...stylex.props(s.projectCardFoot)}>
                      <span {...stylex.props(s.statusDotWrap)}>
                        <span
                          {...stylex.props(
                            s.statusDot,
                            project.status === "done"
                              ? s.statusDotDone
                              : project.status === "active"
                                ? s.statusDotActive
                                : null,
                          )}
                        />
                        {project.meta}
                      </span>
                      <span {...stylex.props(s.projectCardAge)}>
                        {project.updated}
                      </span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* 3. Workspace slice: Sources panel + Kit controls + Mini canvas echo */}
        <section {...stylex.props(s.block)}>
          <div {...stylex.props(s.blockHead)}>
            <h2 {...stylex.props(s.blockTitle)}>
              3 · Panel, kit controls &amp; canvas harmony
            </h2>
            <span {...stylex.props(s.blockNote)}>
              Real <code>src/components/ui</code> parts sitting next to a
              miniature canvas card so surfaces, borders, radii, and accents can
              be judged together.
            </span>
          </div>

          <div {...stylex.props(s.split)}>
            {/* Left: 340px Sources panel */}
            <aside {...stylex.props(s.sidePanel)}>
              <div {...stylex.props(s.sidePanelHead)}>
                <SegmentedControl
                  aria-label="Panel section"
                  size="sm"
                  value={panelTab}
                  onValueChange={setPanelTab}
                  options={[
                    { value: "sources", label: "Sources" },
                    { value: "results", label: "Outputs" },
                  ]}
                  xstyle={s.flex1}
                />
                <Button size="sm" variant="secondary">
                  <Upload size={12} />
                  Add
                </Button>
              </div>

              <div {...stylex.props(s.tree)}>
                <div {...stylex.props(s.folderRow)}>
                  <FolderOpen size={14} {...stylex.props(s.folderIcon)} />
                  <span>1886 Mohylew · Spis wołostiej</span>
                  <span {...stylex.props(s.treeCount)}>2</span>
                </div>
                {(["volost_p01.jpg", "volost_p02.jpg"] as const).map((file) => {
                  const active = selectedFile === file;
                  return (
                    <button
                      key={file}
                      type="button"
                      onClick={() => setSelectedFile(file)}
                      {...stylex.props(
                        s.fileRow,
                        active ? s.fileRowActive : null,
                      )}
                    >
                      <span {...stylex.props(s.miniThumb)}>
                        <ArchivalThumb variant="table" compact />
                      </span>
                      <span {...stylex.props(s.fileCopy)}>
                        <span {...stylex.props(s.fileName)}>{file}</span>
                        <span {...stylex.props(s.fileMeta)}>
                          2480 × 3508 · JPEG
                        </span>
                      </span>
                    </button>
                  );
                })}
                <div {...stylex.props(s.folderRow)}>
                  <Folder size={14} {...stylex.props(s.folderIcon)} />
                  <span>Weryfikacja ręczna</span>
                  <span {...stylex.props(s.treeCount)}>4</span>
                </div>
              </div>

              <div {...stylex.props(s.sidePanelFoot)}>
                <Button size="sm" variant="dashed" block>
                  <Plus size={12} />
                  Drop scans or PDFs here
                </Button>
              </div>
            </aside>

            {/* Middle: Settings / Provider dialog controls slice */}
            <div {...stylex.props(s.plate, s.controlsPlate)}>
              <div {...stylex.props(s.controlsHeader)}>
                <div>
                  <h3 {...stylex.props(s.plateHeading)}>OCR provider setup</h3>
                  <p {...stylex.props(s.controlsSub)}>
                    Shared across projects in Mohylew 1886.
                  </p>
                </div>
                <div {...stylex.props(s.iconRow)}>
                  <IconButton
                    label="Provider settings"
                    size="sm"
                    variant="ghost"
                    pressed
                  >
                    <Settings2 size={14} />
                  </IconButton>
                  <IconButton label="API key" size="sm" variant="soft">
                    <KeyRound size={14} />
                  </IconButton>
                </div>
              </div>

              <div {...stylex.props(s.formGrid)}>
                <Field label="Provider">
                  <Select
                    value={provider}
                    onChange={(event) => setProvider(event.currentTarget.value)}
                  >
                    <option value="mistral">Mistral OCR · ocr-latest</option>
                    <option value="reducto">Reducto · table-v2</option>
                    <option value="gemini">Gemini 2.5 Pro · vision</option>
                  </Select>
                </Field>

                <Field
                  label="Extraction mode"
                  description="Dense variant matches canvas cards."
                >
                  <SegmentedControl
                    aria-label="Extraction mode"
                    size="md"
                    value={ocrMode}
                    onValueChange={setOcrMode}
                    options={[
                      { value: "table", label: "Table" },
                      { value: "text", label: "Prose" },
                      { value: "boxes", label: "Regions" },
                    ]}
                  />
                </Field>

                <Field
                  label="API key"
                  aside="Configured"
                  description="Stored encrypted for this team."
                >
                  <TextInput
                    type="password"
                    mono
                    defaultValue="msk_live_94f1e2c8"
                  />
                </Field>

                <Field
                  label="Custom endpoint"
                  error="Provider returned 401 — verify key or workspace quota."
                >
                  <TextInput mono defaultValue="https://api.mistral.ai/v1" />
                </Field>
              </div>

              <div {...stylex.props(s.togglesRow)}>
                <Switch
                  size="md"
                  label="Auto-deskew archival scans"
                  checked={autoDeskew}
                  onCheckedChange={setAutoDeskew}
                />
                <Checkbox
                  size="md"
                  label="Preserve column alignment"
                  checked={keepLayout}
                  onCheckedChange={setKeepLayout}
                />
              </div>

              <Slider
                label="Region confidence threshold"
                value={confidence}
                min={0.5}
                max={1}
                step={0.01}
                onValueChange={setConfidence}
              />

              <div {...stylex.props(s.noticesRow)}>
                <Notice tone="neutral">
                  2 pages queued — estimated cost $0.004.
                </Notice>
                <Notice tone="warning">
                  Low contrast detected on page 2 header.
                </Notice>
              </div>

              <div {...stylex.props(s.buttonStrip)}>
                <Button size="sm" variant="primary">
                  Save &amp; run
                </Button>
                <Button size="sm" variant="secondary">
                  Test key
                </Button>
                <Button size="sm" variant="soft">
                  Soft
                </Button>
                <Button size="sm" variant="ghost">
                  Cancel
                </Button>
                <Button size="sm" variant="danger">
                  Revoke
                </Button>
                <Button size="sm" variant="primary" disabled>
                  Disabled
                </Button>
              </div>
            </div>

            {/* Right: Miniature canvas echo (to judge harmony against real nodes) */}
            <div {...stylex.props(s.miniCanvas)}>
              <span {...stylex.props(s.miniCanvasTag)}>Canvas reference</span>
              <div {...stylex.props(s.miniCanvasRow)}>
                <div {...stylex.props(s.scanCard)}>
                  <div {...stylex.props(s.scanCardCap)}>
                    <span>JPEG image</span>
                    <span {...stylex.props(s.scanCardCount)}>2 items</span>
                  </div>
                  <div {...stylex.props(s.scanCardFrame)}>
                    <ArchivalThumb variant="table" />
                  </div>
                </div>

                <div {...stylex.props(s.nodeCard)}>
                  <div {...stylex.props(s.nodeCardHead)}>
                    <span {...stylex.props(s.nodeCardTitle)}>
                      Read with Mistral
                    </span>
                    <KeyRound size={12} {...stylex.props(s.nodeKeyIcon)} />
                  </div>
                  <Surface
                    tone="raised"
                    padding="md"
                    shape="lg"
                    xstyle={s.nodeSurface}
                  >
                    <div {...stylex.props(s.portRow)}>
                      <span {...stylex.props(s.portLabel)}>
                        <span {...stylex.props(s.portDotAmber)} />
                        Document link
                      </span>
                      <span {...stylex.props(s.portLabel)}>
                        Transcription
                        <span {...stylex.props(s.portDotAmber)} />
                      </span>
                    </div>
                    <div {...stylex.props(s.portRow)}>
                      <span {...stylex.props(s.portLabel)}>
                        <span {...stylex.props(s.portDotEmerald)} />
                        Scan or PDF
                      </span>
                      <span {...stylex.props(s.portLabel)}>
                        Text blocks
                        <span {...stylex.props(s.portDotEmerald)} />
                      </span>
                    </div>
                    <div {...stylex.props(s.nodeDenseControls)}>
                      <SegmentedControl
                        aria-label="Card dense mode"
                        size="dense"
                        value={ocrMode}
                        onValueChange={setOcrMode}
                        options={[
                          { value: "table", label: "Table" },
                          { value: "text", label: "Prose" },
                          { value: "boxes", label: "Boxes" },
                        ]}
                      />
                    </div>
                  </Surface>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

/** Crisp, understated grayscale SVG facsimile of archival material (zero external assets). */
function ArchivalThumb({
  variant,
  compact = false,
}: {
  variant: "table" | "script" | "map";
  compact?: boolean;
}) {
  return (
    <svg
      viewBox="0 0 120 156"
      width="100%"
      height="100%"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <rect x="0" y="0" width="120" height="156" rx="4" fill="#1E2023" />
      <rect x="4" y="4" width="112" height="148" rx="3" fill="#E6E7E9" />
      <rect x="8" y="8" width="104" height="140" fill="#EFF0F2" />
      {variant === "table" ? (
        <>
          <rect x="34" y="16" width="52" height="3.5" rx="1" fill="#555A62" />
          <rect x="24" y="24" width="72" height="2" rx="1" fill="#8C929C" />
          <line
            x1="14"
            y1="34"
            x2="106"
            y2="34"
            stroke="#737982"
            strokeWidth="1"
          />
          <line
            x1="14"
            y1="48"
            x2="106"
            y2="48"
            stroke="#9BA1AA"
            strokeWidth="0.8"
          />
          <line
            x1="44"
            y1="34"
            x2="44"
            y2="138"
            stroke="#9BA1AA"
            strokeWidth="0.7"
          />
          <line
            x1="78"
            y1="34"
            x2="78"
            y2="138"
            stroke="#9BA1AA"
            strokeWidth="0.7"
          />
          {!compact &&
            [56, 65, 74, 83, 92, 101, 110, 119, 128].map((y) => (
              <g key={y}>
                <rect x="17" y={y} width="22" height="2" fill="#888E98" />
                <rect x="49" y={y} width="24" height="2" fill="#A0A6B0" />
                <rect x="83" y={y} width="16" height="2" fill="#888E98" />
              </g>
            ))}
          <ellipse
            cx="94"
            cy="20"
            rx="10"
            ry="6"
            fill="none"
            stroke="#9EA4AD"
            strokeWidth="0.8"
          />
        </>
      ) : variant === "script" ? (
        <>
          <rect x="28" y="18" width="64" height="4" rx="1" fill="#5B6068" />
          {[34, 46, 58, 70, 82, 94, 106, 118, 130].map((y, idx) => (
            <rect
              key={y}
              x="16"
              y={y}
              width={idx % 3 === 2 ? 64 : 86}
              height="2.2"
              rx="1"
              fill="#8D939D"
            />
          ))}
        </>
      ) : (
        <>
          <path
            d="M14 44 C38 30, 56 64, 106 48"
            fill="none"
            stroke="#6C737E"
            strokeWidth="1.2"
          />
          <path
            d="M14 96 C44 82, 72 114, 106 90"
            fill="none"
            stroke="#8B929D"
            strokeWidth="1"
          />
          <path
            d="M42 14 L54 142 M78 14 L70 142"
            fill="none"
            stroke="#B4B9C2"
            strokeWidth="0.8"
            strokeDasharray="3 3"
          />
          <circle cx="58" cy="72" r="14" fill="none" stroke="#6C737E" />
        </>
      )}
    </svg>
  );
}

const s = stylex.create({
  shell: {
    minHeight: "100svh",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
    fontFamily: "var(--font-geist-sans)",
  },
  bar: {
    position: "sticky",
    top: 0,
    zIndex: 20,
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    padding: "10px 20px",
    backgroundColor: tokens.colorFlowControls,
    backdropFilter: "blur(10px)",
    WebkitBackdropFilter: "blur(10px)",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  barLeft: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    flexWrap: "wrap",
  },
  barBack: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    textDecoration: "none",
  },
  barSlash: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
  },
  barTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  barHint: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    paddingLeft: "6px",
  },
  barRight: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  canvas: {
    maxWidth: "1260px",
    marginInline: "auto",
    padding: "24px 20px 64px",
    display: "flex",
    flexDirection: "column",
    gap: "28px",
  },
  block: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  blockHead: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "baseline",
    gap: "10px",
  },
  blockTitle: {
    margin: 0,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
    color: tokens.colorTextEmphasis,
    letterSpacing: "-0.01em",
  },
  blockNote: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorSubtle,
  },
  chromeStage: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    padding: "18px 20px",
    borderRadius: tokens.radiusLg,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    backgroundColor: tokens.colorBg,
    backgroundImage: `radial-gradient(${tokens.colorGrid} 1px, transparent 1px)`,
    backgroundSize: "16px 16px",
  },
  floatingPill: {
    display: "inline-flex",
    alignItems: "center",
    gap: "8px",
    padding: "6px 10px",
    borderRadius: tokens.radiusLg,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
  },
  pillDivider: {
    width: "1px",
    height: "16px",
    backgroundColor: tokens.colorDivider,
  },
  crumbButton: {
    borderWidth: 0,
    padding: "2px 6px",
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontFamily: "inherit",
    cursor: "pointer",
  },
  crumbChevron: {
    color: tokens.colorSubtle,
  },
  projectTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  savedBadge: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    padding: "2px 7px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  plate: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    padding: "16px",
    borderRadius: tokens.radiusLg,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
  },
  plateToolbar: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
  },
  plateHeadingGroup: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  plateHeading: {
    margin: 0,
    fontSize: "15px",
    fontWeight: 600,
    color: tokens.colorTextEmphasis,
    letterSpacing: "-0.015em",
  },
  countPill: {
    padding: "1px 7px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    fontVariantNumeric: "tabular-nums",
  },
  plateActions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "8px",
  },
  searchWrap: {
    position: "relative",
    width: "210px",
  },
  searchIcon: {
    position: "absolute",
    left: "9px",
    top: "50%",
    transform: "translateY(-50%)",
    color: tokens.colorSubtle,
    pointerEvents: "none",
  },
  searchInput: {
    height: "28px",
    paddingLeft: "28px",
    fontSize: tokens.fontSizeXs,
  },
  projectGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
    gap: "12px",
  },
  projectCard: {
    display: "grid",
    gridTemplateColumns: "62px minmax(0, 1fr)",
    gap: "12px",
    padding: "10px",
    borderRadius: tokens.radiusMd,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    backgroundColor: {
      default: tokens.colorBg,
      ":hover": tokens.colorSurfaceRaised,
    },
    transitionProperty: "background-color, border-color",
    transitionDuration: "120ms",
  },
  thumbFrame: {
    width: "62px",
    height: "80px",
    borderRadius: tokens.radiusSm,
    overflow: "hidden",
    boxShadow: tokens.shadowNode,
  },
  projectCardBody: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    gap: "4px",
  },
  projectCardTop: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "6px",
  },
  projectCardName: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
    lineHeight: 1.3,
  },
  projectCardMeta: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  projectCardFoot: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingTop: "4px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  statusDotWrap: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  statusDot: {
    width: "7px",
    height: "7px",
    borderRadius: "9999px",
    flexShrink: 0,
    backgroundColor: tokens.colorBorderStrong,
  },
  statusDotDone: {
    backgroundColor: tokens.colorSuccess,
  },
  statusDotActive: {
    backgroundColor: tokens.colorWarning,
  },
  projectCardAge: {
    flexShrink: 0,
    fontVariantNumeric: "tabular-nums",
  },
  split: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
    gap: "16px",
    alignItems: "start",
  },
  sidePanel: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    padding: "14px",
    borderRadius: tokens.radiusLg,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
  },
  sidePanelHead: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  flex1: {
    flex: 1,
  },
  tree: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  folderRow: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    padding: "6px 8px",
    borderRadius: tokens.radiusMd,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  folderIcon: {
    color: tokens.colorMuted,
    flexShrink: 0,
  },
  treeCount: {
    marginLeft: "auto",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontVariantNumeric: "tabular-nums",
  },
  fileRow: {
    display: "flex",
    alignItems: "center",
    gap: "9px",
    marginLeft: "14px",
    padding: "6px 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "transparent",
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorText,
    textAlign: "left",
    fontFamily: "inherit",
    cursor: "pointer",
  },
  fileRowActive: {
    backgroundColor: tokens.colorSurfaceRaised,
    borderColor: tokens.colorDivider,
  },
  miniThumb: {
    width: "24px",
    height: "31px",
    flexShrink: 0,
    borderRadius: "3px",
    overflow: "hidden",
  },
  fileCopy: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: "1px",
  },
  fileName: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    color: tokens.colorTextEmphasis,
  },
  fileMeta: {
    fontSize: "10px",
    color: tokens.colorSubtle,
    fontVariantNumeric: "tabular-nums",
  },
  sidePanelFoot: {
    paddingTop: "4px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  controlsPlate: {
    gap: "14px",
  },
  controlsHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "10px",
  },
  controlsSub: {
    margin: "2px 0 0",
    fontSize: tokens.fontSizeXs,
    color: tokens.colorSubtle,
  },
  iconRow: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  formGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    gap: "12px",
  },
  togglesRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "16px",
    paddingBlock: "4px",
  },
  noticesRow: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  buttonStrip: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: "8px",
    paddingTop: "8px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  miniCanvas: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    padding: "16px",
    borderRadius: tokens.radiusLg,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    backgroundColor: tokens.colorBg,
    backgroundImage: `radial-gradient(${tokens.colorGrid} 1px, transparent 1px)`,
    backgroundSize: "16px 16px",
  },
  miniCanvasTag: {
    alignSelf: "flex-start",
    padding: "2px 8px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurface,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 500,
  },
  miniCanvasRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "flex-start",
    gap: "14px",
  },
  scanCard: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    width: "96px",
  },
  scanCardCap: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: "10px",
    color: tokens.colorMuted,
  },
  scanCardCount: {
    color: tokens.colorSubtle,
  },
  scanCardFrame: {
    width: "96px",
    height: "124px",
    borderRadius: tokens.radiusMd,
    overflow: "hidden",
    boxShadow: tokens.shadowNodeRaised,
  },
  nodeCard: {
    flex: "1 1 200px",
    display: "flex",
    flexDirection: "column",
    gap: "5px",
  },
  nodeCardHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    paddingInline: "2px",
  },
  nodeCardTitle: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    color: tokens.colorMuted,
  },
  nodeKeyIcon: {
    color: tokens.colorSuccess,
  },
  nodeSurface: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
    boxShadow: tokens.shadowNodeRaised,
  },
  portRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  portLabel: {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    color: tokens.colorText,
  },
  portDotAmber: {
    width: "9px",
    height: "9px",
    borderRadius: "9999px",
    borderWidth: 2,
    borderStyle: "solid",
    borderColor: tokens.colorWarning,
    backgroundColor: tokens.colorSurface,
  },
  portDotEmerald: {
    width: "9px",
    height: "9px",
    borderRadius: "9999px",
    borderWidth: 2,
    borderStyle: "solid",
    borderColor: tokens.colorSuccess,
    backgroundColor: tokens.colorSurface,
  },
  nodeDenseControls: {
    paddingTop: "8px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
});
