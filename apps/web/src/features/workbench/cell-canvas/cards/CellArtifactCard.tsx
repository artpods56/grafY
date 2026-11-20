"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  FileText,
  ImageIcon,
  Map as MapIcon,
  Plus,
  ScanSearch,
  Trash2,
  X,
} from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CellCardToolbar } from "../CellCanvasContext";
import type {
  ArtifactCardSurfaceData,
  CollectionCardSurfaceData,
} from "../cell-contracts";
import { CELL_SIZE } from "../cell-model";
import {
  CellCardShell,
  cellCardMarks as m,
  plateRowTop,
  stopCardDrag,
  styled,
  useResolvedCardState,
  type CellCardBaseProps,
} from "./CellOperatorCard";

/**
 * Artifact and collection cards on the cell canvas. Both are whole-cell
 * boxes with the shared card shell: their ports sit on the card's own edges,
 * in the glass stage's wells, with no rail floating outside the card.
 */

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

const s = stylex.create({
  headerMeta: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "10px",
    whiteSpace: "nowrap",
  },
  stripLabel: {
    flexShrink: 0,
    color: tokens.colorMuted,
    fontWeight: 500,
  },
  stripFilename: {
    flexGrow: 1,
    textAlign: "right",
  },
  // Below the 23px strip, to the plate's lower edge.
  preview: {
    position: "absolute",
    top: "23px",
    left: 0,
    right: 0,
    bottom: 0,
    overflow: "hidden",
  },
  checker: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: tokens.colorSurfaceSunken,
    backgroundImage: `repeating-conic-gradient(${tokens.colorSurfaceRaised} 0% 25%, transparent 0% 50%)`,
    backgroundSize: "14px 14px",
  },
  image: {
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "contain",
    pointerEvents: "none",
    userSelect: "none",
  },
  placeholder: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    maxWidth: "100%",
    paddingInline: "12px",
    boxSizing: "border-box",
    color: tokens.colorSubtle,
    fontSize: "10px",
    textAlign: "center",
  },
  placeholderMeta: {
    fontFamily: MONO_FONT,
    fontSize: "9px",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    tableLayout: "fixed",
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
    lineHeight: 1.4,
    color: tokens.colorText,
  },
  th: {
    position: "sticky",
    top: 0,
    paddingBlock: "3px",
    paddingInline: "6px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontWeight: 600,
    textAlign: "left",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  td: {
    paddingBlock: "2px",
    paddingInline: "6px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  cellDivider: {
    borderLeftWidth: "1px",
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorDivider,
  },
  reading: {
    boxSizing: "border-box",
    height: "100%",
    paddingBlock: "8px",
    paddingInline: "10px",
    color: tokens.colorText,
    fontSize: "10.5px",
    lineHeight: 1.5,
    overflowWrap: "anywhere",
  },
  readingLine: { margin: 0, minHeight: "1em" },
  readingHeading: { fontWeight: 600, fontSize: "11.5px" },
  readingBullet: { paddingLeft: "10px" },
  fileBody: {
    boxSizing: "border-box",
    height: "100%",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    paddingInline: "12px",
  },
  fileIcon: {
    flexShrink: 0,
    width: "34px",
    height: "40px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: tokens.radiusSm,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
  },
  fileText: {
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  fileName: {
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    color: tokens.colorText,
  },
  fileMeta: {
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
    color: tokens.colorSubtle,
  },
  map: {
    position: "relative",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  mapArt: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
  },
  mapLegend: {
    position: "absolute",
    left: "8px",
    right: "8px",
    bottom: "6px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    color: tokens.colorMuted,
    fontSize: "9.5px",
  },
  mapCaption: {
    position: "absolute",
    top: "6px",
    left: "8px",
    right: "8px",
    color: tokens.colorSubtle,
    fontSize: "9.5px",
  },
  toolbarType: {
    paddingInline: "6px",
    color: tokens.colorMuted,
    fontSize: "10px",
    whiteSpace: "nowrap",
  },

  memberRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px 6px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    fontSize: tokens.fontSizeXs,
  },
  memberText: {
    minWidth: 0,
    flexGrow: 1,
    flexBasis: 0,
    display: "flex",
    flexDirection: "column",
    gap: "1px",
  },
  memberLabel: { color: tokens.colorText },
  memberType: { color: tokens.colorSubtle, fontSize: "9.5px" },
  memberMeta: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "9.5px",
  },
  spareRow: {
    display: "flex",
    alignItems: "center",
    paddingBlock: "8px",
    paddingInline: "10px",
  },
  spareSlot: {
    flexGrow: 1,
    height: "100%",
    boxSizing: "border-box",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
});

function TypeDot({ artifactTypeId }: { artifactTypeId: string }) {
  return (
    <span
      aria-hidden="true"
      {...styled(
        {
          backgroundColor: artifactTypeColor(artifactTypeId, tokens.colorMuted),
        },
        m.dot,
      )}
    />
  );
}

// --- Artifact card ---------------------------------------------------------

export interface CellArtifactCardProps extends CellCardBaseProps {
  surface: ArtifactCardSurfaceData;
  onInspect?: (cardId: string) => void;
  onRemove?: (cardId: string) => void;
}

function CellArtifactCardImpl(props: CellArtifactCardProps) {
  const { card, surface, onInspect, onRemove } = props;
  const state = useResolvedCardState(card.id, props);
  const headerMeta = surface.dimensionsLabel ?? surface.byteSizeLabel;
  const stripDetail = surface.filename ?? card.subtitle;

  return (
    <CellCardShell
      {...props}
      kind="artifact"
      state={state}
      resizable={card.resizable ?? true}
      rootData={{ "data-artifact-type": surface.artifactTypeId }}
      headerExtra={
        headerMeta ? (
          <span {...stylex.props(s.headerMeta)}>{headerMeta}</span>
        ) : null
      }
      strip={
        <>
          <TypeDot artifactTypeId={surface.artifactTypeId} />
          <span {...stylex.props(s.stripLabel)}>{surface.typeLabel}</span>
          {stripDetail ? (
            <span {...stylex.props(m.ellipsis, s.stripFilename)}>
              {stripDetail}
            </span>
          ) : null}
        </>
      }
      toolbar={
        <CellCardToolbar visible={state.selected} position="top">
          <span {...stylex.props(s.toolbarType)}>{surface.typeLabel}</span>
          {onInspect ? (
            <IconButton
              size="2xs"
              variant="ghost"
              label={`Inspect ${card.title}`}
              onPointerDown={stopCardDrag}
              onClick={() => onInspect(card.id)}
            >
              <ScanSearch size={11} />
            </IconButton>
          ) : null}
          {onRemove ? (
            <IconButton
              size="2xs"
              variant="danger"
              label={`Remove ${card.title}`}
              onPointerDown={stopCardDrag}
              onClick={() => onRemove(card.id)}
            >
              <Trash2 size={11} />
            </IconButton>
          ) : null}
        </CellCardToolbar>
      }
    >
      <div
        data-artifact-preview={surface.previewKind}
        {...stylex.props(
          s.preview,
          surface.previewKind === "image" && s.checker,
          surface.previewKind === "map" && s.map,
        )}
      >
        <ArtifactPreview card={card} surface={surface} />
      </div>
    </CellCardShell>
  );
}

function ArtifactPreview({
  card,
  surface,
}: {
  card: CellArtifactCardProps["card"];
  surface: ArtifactCardSurfaceData;
}) {
  switch (surface.previewKind) {
    case "image":
      return surface.imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer
        <img
          src={surface.imageUrl}
          alt={surface.filename ?? card.title}
          draggable={false}
          {...stylex.props(s.image)}
        />
      ) : (
        <div {...stylex.props(s.placeholder)}>
          <ImageIcon size={18} aria-hidden="true" />
          {surface.filename ? (
            <span {...stylex.props(m.ellipsis)}>{surface.filename}</span>
          ) : null}
          {surface.dimensionsLabel ? (
            <span {...stylex.props(s.placeholderMeta)}>
              {surface.dimensionsLabel}
            </span>
          ) : null}
        </div>
      );
    case "table": {
      const headers = surface.tableHeaders ?? [];
      const rows = surface.tableRows ?? [];
      return (
        <table {...stylex.props(s.table)}>
          {headers.length ? (
            <thead>
              <tr>
                {headers.map((header, index) => (
                  <th
                    key={index}
                    scope="col"
                    {...stylex.props(s.th, index > 0 && s.cellDivider)}
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
          ) : null}
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((value, index) => (
                  <td
                    key={index}
                    {...stylex.props(s.td, index > 0 && s.cellDivider)}
                  >
                    {value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    }
    case "markdown":
      return <ReadingPreview text={surface.previewText ?? ""} />;
    case "file":
      return (
        <div {...stylex.props(s.fileBody)}>
          <span aria-hidden="true" {...stylex.props(s.fileIcon)}>
            <FileText size={18} />
          </span>
          <span {...stylex.props(s.fileText)}>
            <span {...stylex.props(s.fileName, m.ellipsis)}>
              {surface.filename ?? card.title}
            </span>
            <span {...stylex.props(s.fileMeta, m.ellipsis)}>
              {surface.typeLabel}
              {surface.byteSizeLabel ? ` · ${surface.byteSizeLabel}` : ""}
            </span>
          </span>
        </div>
      );
    case "map":
      return (
        <>
          <MapMotif />
          {surface.previewText ? (
            <span {...stylex.props(s.mapCaption, m.ellipsis)}>
              {surface.previewText}
            </span>
          ) : null}
          <span {...stylex.props(s.mapLegend)}>
            <MapIcon size={11} aria-hidden="true" />
            <span {...stylex.props(m.ellipsis, m.grow)}>
              {surface.typeLabel}
            </span>
            {surface.dimensionsLabel ? (
              <span {...stylex.props(s.placeholderMeta)}>
                {surface.dimensionsLabel}
              </span>
            ) : null}
          </span>
        </>
      );
  }
}

/**
 * Markdown read as plain text: `#` lines set as headings and `-` / `*` lines as
 * bullets. The card shows a glance, not a rendered document.
 */
function ReadingPreview({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div {...stylex.props(s.reading)}>
      {lines.map((line, index) => {
        const heading = /^#{1,6}\s+/.exec(line);
        if (heading) {
          return (
            <p key={index} {...stylex.props(s.readingLine, s.readingHeading)}>
              {line.slice(heading[0].length)}
            </p>
          );
        }
        const bullet = /^\s*[-*]\s+/.exec(line);
        if (bullet) {
          return (
            <p key={index} {...stylex.props(s.readingLine, s.readingBullet)}>
              • {line.slice(bullet[0].length)}
            </p>
          );
        }
        return (
          <p key={index} {...stylex.props(s.readingLine)}>
            {line}
          </p>
        );
      })}
    </div>
  );
}

/** A coordinate grid with contour lines: a map layer's mark, not its data. */
function MapMotif() {
  const grid = [20, 40, 60, 80];
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      {...stylex.props(s.mapArt)}
    >
      <g
        style={{ stroke: tokens.colorDivider }}
        strokeWidth={0.4}
        vectorEffect="non-scaling-stroke"
      >
        {grid.map((at) => (
          <React.Fragment key={at}>
            <line x1={at} y1={0} x2={at} y2={100} />
            <line x1={0} y1={at} x2={100} y2={at} />
          </React.Fragment>
        ))}
      </g>
      <g
        fill="none"
        style={{ stroke: tokens.colorBorderStrong }}
        strokeOpacity={0.45}
        strokeWidth={0.8}
      >
        <path d="M8 70 C 22 52, 40 60, 52 44 S 82 30, 94 38" />
        <path d="M14 82 C 30 66, 46 74, 60 58 S 84 50, 96 54" />
        <path d="M30 30 C 40 22, 54 24, 58 32 S 46 46, 36 42 S 24 36, 30 30 Z" />
      </g>
    </svg>
  );
}

export const CellArtifactCard = React.memo(CellArtifactCardImpl);

// --- Collection card -------------------------------------------------------

export interface CellCollectionCardProps extends CellCardBaseProps {
  surface: CollectionCardSurfaceData;
  onRemoveMember?: (cardId: string, memberId: string) => void;
}

function CellCollectionCardImpl(props: CellCollectionCardProps) {
  const { card, surface, onRemoveMember } = props;
  const state = useResolvedCardState(card.id, props);
  const count = surface.members.length;
  const spareRowOffset = count + 1;

  return (
    <CellCardShell
      {...props}
      kind="collection"
      state={state}
      resizable={card.resizable ?? true}
      rootData={{ "data-artifact-type": surface.artifactTypeId }}
      headerExtra={
        <span data-collection-count={count} {...stylex.props(m.chip)}>
          {count === 1 ? "1 item" : `${count} items`}
        </span>
      }
      strip={
        <>
          <TypeDot artifactTypeId={surface.artifactTypeId} />
          <span {...stylex.props(s.stripLabel, m.ellipsis)}>
            {surface.typeLabel}
          </span>
        </>
      }
    >
      {surface.members.map((member, index) => (
        <div
          key={member.id}
          data-collection-member={member.id}
          {...styled(
            { top: plateRowTop(index + 1), height: CELL_SIZE },
            m.band,
            s.memberRow,
          )}
        >
          <span {...stylex.props(m.indexBadge)}>{index + 1}</span>
          <TypeDot artifactTypeId={member.artifactTypeId} />
          <span {...stylex.props(s.memberText)}>
            <span {...stylex.props(s.memberLabel, m.ellipsis)}>
              {member.label}
            </span>
            <span {...stylex.props(s.memberType, m.ellipsis)}>
              {member.typeLabel}
            </span>
          </span>
          {member.meta ? (
            <span {...stylex.props(s.memberMeta)}>{member.meta}</span>
          ) : null}
          {onRemoveMember ? (
            <IconButton
              size="2xs"
              variant="ghost"
              label={`Remove ${member.label}`}
              onPointerDown={stopCardDrag}
              onClick={() => onRemoveMember(card.id, member.id)}
            >
              <X size={11} />
            </IconButton>
          ) : null}
        </div>
      ))}
      {surface.showSparePlug ? (
        <div
          data-collection-spare-plug="true"
          {...styled(
            { top: plateRowTop(spareRowOffset), height: CELL_SIZE },
            m.band,
            s.spareRow,
          )}
        >
          <span {...stylex.props(s.spareSlot)}>
            <Plus size={11} aria-hidden="true" />
            Drop / wire item
          </span>
        </div>
      ) : null}
    </CellCardShell>
  );
}

export const CellCollectionCard = React.memo(CellCollectionCardImpl);
