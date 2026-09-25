"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { Download, Link2, MoreHorizontal } from "lucide-react";

import { artifactContentUrl } from "@/lib/api";
import { writeArtifactDrop } from "../../../model/artifact-drop";
import {
  BLOB_ARTIFACT_NOTICE,
  isBlobArtifact,
} from "../../../model/blob-notice";
import { panelStyles as s } from "../panel-styles";
import {
  isItemImage,
  libraryFileDisplayName,
  libraryFileSubtitle,
  type LibraryFileNode,
} from "../library-tree";
import { FILE_ICONS } from "./file-icons";
import { MenuItem } from "./MenuItem";
import { isRowAction } from "./row-controls";

export function LibraryFileRow({
  file,
  workspaceId,
  selected,
  tabbable,
  onFocusRow,
  onSelect,
}: {
  file: LibraryFileNode;
  workspaceId: string;
  selected: boolean;
  tabbable: boolean;
  onFocusRow: () => void;
  onSelect: () => void;
}) {
  const { item } = file;
  const displayName = libraryFileDisplayName(item);
  const contentUrl = artifactContentUrl(workspaceId, item.artifact.content_url);
  const TypeIcon = FILE_ICONS[file.icon];
  const [thumbnailFailed, setThumbnailFailed] = React.useState(false);

  return (
    <div
      role="treeitem"
      aria-level={file.depth + 1}
      aria-selected={selected}
      draggable
      data-tree-key={file.key}
      data-tree-label={displayName}
      data-artifact-id={item.artifact.artifact_id}
      tabIndex={tabbable ? 0 : -1}
      title={`${displayName} — drag onto an input or a folder, or double-click to open`}
      onFocus={onFocusRow}
      onClick={(event) => {
        if (isRowAction(event)) return;
        onSelect();
      }}
      onDoubleClick={() => {
        if (contentUrl) window.open(contentUrl, "_blank", "noopener");
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onSelect();
      }}
      onDragStart={(event) => {
        writeArtifactDrop(event.dataTransfer, {
          artifact_id: item.artifact.artifact_id,
          artifact_type: item.artifact.artifact_type,
          schema_version: item.artifact.schema_version,
          content_hash: item.artifact.sha256 ?? null,
        });
        event.dataTransfer.effectAllowed = "copyMove";
        onSelect();
      }}
      {...stylex.props(s.fileRow, selected ? s.fileRowSelected : null)}
    >
      <span {...stylex.props(s.fileThumb)}>
        {isItemImage(item) && contentUrl !== null && !thumbnailFailed ? (
          /* eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer */
          <img
            src={contentUrl}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setThumbnailFailed(true)}
            {...stylex.props(s.fileThumbImage)}
          />
        ) : (
          <TypeIcon size={11} aria-hidden="true" />
        )}
      </span>
      <span {...stylex.props(s.fileCopy)}>
        <span {...stylex.props(s.fileName)}>{displayName}</span>
        <span {...stylex.props(s.fileMeta)}>{libraryFileSubtitle(item)}</span>
        {isBlobArtifact(item.artifact) ? (
          <span role="status" {...stylex.props(s.fileMeta)}>
            {BLOB_ARTIFACT_NOTICE}
          </span>
        ) : null}
      </span>
      <Menu.Root>
        <Menu.Trigger
          aria-label={`Actions for ${displayName}`}
          {...stylex.props(s.rowActions)}
        >
          <MoreHorizontal size={13} />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Positioner
            side="bottom"
            align="end"
            sideOffset={4}
            {...stylex.props(s.menuPositioner)}
          >
            <Menu.Popup {...stylex.props(s.menu)}>
              <MenuItem
                icon={Download}
                label="Open original"
                disabled={contentUrl === null}
                onSelect={() => {
                  if (contentUrl) window.open(contentUrl, "_blank", "noopener");
                }}
              />
              <MenuItem
                icon={Link2}
                label="Copy link"
                disabled={contentUrl === null}
                onSelect={() => {
                  if (contentUrl)
                    void navigator.clipboard?.writeText(contentUrl);
                }}
              />
            </Menu.Popup>
          </Menu.Positioner>
        </Menu.Portal>
      </Menu.Root>
    </div>
  );
}
