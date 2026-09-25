"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import {
  ChevronRight,
  Folder,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";

import { panelStyles as s } from "../panel-styles";
import type { LibraryFolderNode } from "../library-tree";
import { MenuItem } from "./MenuItem";
import { LibraryFolderRenameInput } from "./LibraryFolderRenameInput";
import {
  dragKind,
  MIME_LIBRARY_FOLDER_ID,
  type DragKind,
} from "./drag-payload";
import { isRowAction } from "./row-controls";

export function LibraryFolderRow({
  folder,
  open,
  renaming,
  dropTarget,
  filtering,
  tabbable,
  renameInputRef,
  onFocusRow,
  onToggle,
  onStartRename,
  onEndRename,
  onRename,
  onCreateSubfolder,
  onDelete,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  folder: LibraryFolderNode;
  open: boolean;
  renaming: boolean;
  dropTarget: boolean;
  filtering: boolean;
  tabbable: boolean;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onFocusRow: () => void;
  onToggle: () => void;
  onStartRename: () => void;
  onEndRename: () => void;
  onRename: (name: string) => Promise<void>;
  onCreateSubfolder: () => void;
  onDelete: () => Promise<void>;
  onDragOver: (kind: DragKind) => void;
  onDragLeave: () => void;
  onDrop: (event: React.DragEvent<HTMLDivElement>) => void;
}) {
  const canDelete = folder.total === 0;

  return (
    <div
      role="treeitem"
      aria-expanded={open}
      aria-selected={false}
      aria-level={folder.depth + 1}
      data-tree-key={folder.key}
      data-tree-label={folder.name}
      data-folder-drop={dropTarget ? "true" : undefined}
      tabIndex={tabbable ? 0 : -1}
      title={folder.name}
      onFocus={onFocusRow}
      onClick={(event) => {
        if (isRowAction(event)) return;
        onToggle();
      }}
      onKeyDown={(event) => {
        if (event.key === "F2") {
          event.preventDefault();
          onStartRename();
        }
      }}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData(MIME_LIBRARY_FOLDER_ID, folder.id);
      }}
      onDragOver={(event) => {
        const kind = dragKind(Array.from(event.dataTransfer.types));
        if (kind === null) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = kind === "upload" ? "copy" : "move";
        onDragOver(kind);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node)) return;
        onDragLeave();
      }}
      onDrop={onDrop}
      {...stylex.props(s.folderRow, dropTarget ? s.rowDropTarget : null)}
      draggable={!renaming}
    >
      <ChevronRight
        size={12}
        aria-hidden="true"
        {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
      />
      <Folder size={13} aria-hidden="true" />
      {renaming ? (
        <LibraryFolderRenameInput
          initialName={folder.name}
          inputRef={renameInputRef}
          onCommit={(name) => void onRename(name).then(onEndRename)}
          onCancel={onEndRename}
        />
      ) : (
        <span {...stylex.props(s.folderName)}>{folder.name}</span>
      )}
      <span {...stylex.props(s.count)}>
        {filtering ? folder.matched : folder.total}
      </span>
      {!renaming ? (
        <Menu.Root>
          <Menu.Trigger
            aria-label={`Actions for ${folder.name}`}
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
                  icon={FolderPlus}
                  label="New subfolder"
                  onSelect={onCreateSubfolder}
                />
                <MenuItem
                  icon={Pencil}
                  label="Rename"
                  onSelect={onStartRename}
                />
                <MenuItem
                  icon={Trash2}
                  label={
                    canDelete
                      ? "Delete folder"
                      : "Delete folder — empty it first"
                  }
                  disabled={!canDelete}
                  onSelect={() => void onDelete()}
                />
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>
      ) : null}
    </div>
  );
}
