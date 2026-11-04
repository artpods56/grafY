"use client";

import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  /**
   * A choice spans the whole row with its detail at the far end. `Button` draws
   * the box, the focus ring and the colours; this only lays out the two lines.
   */
  choice: {
    width: "100%",
    height: "auto",
    minHeight: "44px",
    justifyContent: "space-between",
    gap: "12px",
    paddingBlock: "8px",
    paddingInline: "10px",
    textAlign: "left",
    whiteSpace: "normal",
  },
  choiceTitle: { fontSize: tokens.fontSizeSm, fontWeight: 720 },
  choiceDetail: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textAlign: "right",
  },
  actions: { display: "flex", justifyContent: "flex-end" },
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
                  <Button
                    variant="secondary"
                    size="md"
                    autoFocus
                    xstyle={s.choice}
                    onClick={onPlaceAll}
                  >
                    <span {...stylex.props(s.choiceTitle)}>
                      Create {pending.groups.length} sequences
                    </span>
                    <span {...stylex.props(s.choiceDetail)}>
                      one per artifact type
                    </span>
                  </Button>
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
                    <Button
                      key={`${group.value.artifact_type}@${group.value.schema_version}`}
                      variant="secondary"
                      size="md"
                      autoFocus={!pending.canPlaceAll && index === 0}
                      aria-label={`Place ${title}`}
                      title={artifactCardContractTooltip(group.value)}
                      xstyle={s.choice}
                      onClick={() => onPlaceGroup(group)}
                    >
                      <span {...stylex.props(s.choiceTitle)}>{title}</span>
                      <span {...stylex.props(s.choiceDetail)}>
                        {artifactCount(group)}
                      </span>
                    </Button>
                  );
                })}
              </div>
              <div {...stylex.props(s.actions)}>
                <Button variant="ghost" size="sm" onClick={onClose}>
                  Cancel
                </Button>
              </div>
            </>
          ) : null}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
