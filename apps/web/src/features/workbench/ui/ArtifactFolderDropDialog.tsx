"use client";

import * as stylex from "@stylexjs/stylex";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  artifactCardContract,
  artifactCardContractTooltip,
  cardArtifactRefs,
} from "../canvas/artifact-card";
import { useArtifactTypeCatalog } from "../canvas/use-artifact-type-catalog";
import type { ArtifactDropPayload } from "../model/artifact-drop";

/**
 * A Library folder dropped where it holds more than one artifact type. One
 * card or input holds one type, so the drop cannot place the folder as it is;
 * the user decides what it means.
 */
export interface PendingFolderDrop {
  folderName: string;
  /** The folder's artifacts, one group per type, in the order they were shown. */
  groups: readonly ArtifactDropPayload[];
  /**
   * Whether every group can land at once. Empty canvas takes a card per group;
   * an input row takes one value, so there the user can only pick one group.
   */
  canPlaceAll: boolean;
}

interface ArtifactFolderDropDialogProps {
  pending: PendingFolderDrop | null;
  onPlaceAll: () => void;
  onPlaceGroup: (group: ArtifactDropPayload) => void;
  onClose: () => void;
}

const s = stylex.create({
  prompt: {
    marginBottom: "7px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
  choices: { display: "grid", gap: "6px", marginBottom: "12px" },
  choice: {
    width: "100%",
    minHeight: "44px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "12px",
    padding: "8px 10px",
    borderRadius: "6px",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-3px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    color: tokens.colorText,
    cursor: "pointer",
    textAlign: "left",
  },
  choiceTitle: { fontSize: tokens.fontSizeSm, fontWeight: 720 },
  choiceDetail: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textAlign: "right",
  },
  actions: { display: "flex", justifyContent: "flex-end" },
  cancel: {
    minHeight: "29px",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
  },
});

function artifactCount(group: ArtifactDropPayload): string {
  const count = cardArtifactRefs(group.value).length;
  return count === 1 ? "1 artifact" : `${count} artifacts`;
}

export function ArtifactFolderDropDialog({
  pending,
  onPlaceAll,
  onPlaceGroup,
  onClose,
}: ArtifactFolderDropDialogProps) {
  const artifactTypes = useArtifactTypeCatalog();
  return (
    <Dialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent size="compact">
        <DialogHeader>
          <DialogTitle>
            {pending
              ? `${pending.folderName} holds ${pending.groups.length} kinds of artifact`
              : "Folder holds several kinds of artifact"}
          </DialogTitle>
          <DialogDescription>
            A sequence holds one artifact type, so each type needs its own.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {pending ? (
            <>
              {pending.canPlaceAll ? (
                <div {...stylex.props(s.choices)}>
                  <button
                    type="button"
                    autoFocus
                    {...stylex.props(overlay.item, s.choice)}
                    onClick={onPlaceAll}
                  >
                    <span {...stylex.props(s.choiceTitle)}>
                      Create {pending.groups.length} sequences
                    </span>
                    <span {...stylex.props(s.choiceDetail)}>
                      one per artifact type
                    </span>
                  </button>
                </div>
              ) : null}
              <p {...stylex.props(s.prompt)}>
                {pending.canPlaceAll
                  ? "Or place just one group:"
                  : "Choose which group to place:"}
              </p>
              <div {...stylex.props(s.choices)}>
                {pending.groups.map((group, index) => {
                  const title = artifactCardContract(
                    group.value,
                    artifactTypes,
                  );
                  return (
                    <button
                      key={`${group.value.artifact_type}@${group.value.schema_version}`}
                      type="button"
                      autoFocus={!pending.canPlaceAll && index === 0}
                      aria-label={`Place ${title}`}
                      title={artifactCardContractTooltip(group.value)}
                      {...stylex.props(overlay.item, s.choice)}
                      onClick={() => onPlaceGroup(group)}
                    >
                      <span {...stylex.props(s.choiceTitle)}>{title}</span>
                      <span {...stylex.props(s.choiceDetail)}>
                        {artifactCount(group)}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div {...stylex.props(s.actions)}>
                <button
                  type="button"
                  {...stylex.props(s.cancel)}
                  onClick={onClose}
                >
                  Cancel
                </button>
              </div>
            </>
          ) : null}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
