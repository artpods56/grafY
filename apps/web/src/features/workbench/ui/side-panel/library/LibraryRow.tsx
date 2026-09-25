"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { panelStyles as s } from "../panel-styles";
import type { LibraryTreeNode } from "../library-tree";
import { LibraryFileRow } from "./LibraryFileRow";
import { LibraryFolderRow } from "./LibraryFolderRow";
import {
  dragKind,
  droppedArtifactId,
  MIME_LIBRARY_FOLDER_ID,
} from "./drag-payload";

/** One row, plus the rows it contains when it is an open folder. */
export function LibraryRow({
  node,
  workspaceId,
  collapsedFolders,
  filtering,
  tabbableKey,
  selectedId,
  renamingFolderId,
  dragOverFolderId,
  renameInputRef,
  onToggle,
  onFocusRow,
  onSelect,
  onStartRename,
  onEndRename,
  onRename,
  onCreateSubfolder,
  onDelete,
  onDragOverFolder,
  onMoveFolder,
  onMoveItems,
  onUploadFiles,
}: {
  node: LibraryTreeNode;
  workspaceId: string;
  collapsedFolders: ReadonlySet<string>;
  filtering: boolean;
  tabbableKey: string | null;
  selectedId: string | null;
  renamingFolderId: string | null;
  dragOverFolderId: string | null;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onToggle: (key: string) => void;
  onFocusRow: (key: string) => void;
  onSelect: (artifactId: string) => void;
  onStartRename: (folderId: string) => void;
  onEndRename: () => void;
  onRename: (folderId: string, name: string) => Promise<void>;
  onCreateSubfolder: (parentId: string) => void;
  onDelete: (folderId: string) => Promise<void>;
  onDragOverFolder: (folderId: string | null) => void;
  onMoveFolder: (folderId: string, parentId: string | null) => Promise<void>;
  onMoveItems: (
    artifactIds: readonly string[],
    folderId: string | null,
  ) => Promise<void>;
  onUploadFiles: (files: File[], folderId: string | null) => void;
}) {
  if (node.kind === "file") {
    return (
      <LibraryFileRow
        file={node}
        workspaceId={workspaceId}
        selected={node.item.artifact.artifact_id === selectedId}
        tabbable={tabbableKey === node.key}
        onFocusRow={() => onFocusRow(node.key)}
        onSelect={() => onSelect(node.item.artifact.artifact_id)}
      />
    );
  }

  const collapsed = collapsedFolders.has(node.key);
  const open = !collapsed;

  return (
    <>
      <LibraryFolderRow
        folder={node}
        open={open}
        renaming={renamingFolderId === node.id}
        dropTarget={dragOverFolderId === node.id}
        filtering={filtering}
        tabbable={tabbableKey === node.key}
        renameInputRef={renameInputRef}
        onFocusRow={() => onFocusRow(node.key)}
        onToggle={() => onToggle(node.key)}
        onStartRename={() => onStartRename(node.id)}
        onEndRename={onEndRename}
        onRename={(name) => onRename(node.id, name)}
        onCreateSubfolder={() => onCreateSubfolder(node.id)}
        onDelete={() => onDelete(node.id)}
        onDragOver={(kind) => {
          if (kind === null) return;
          onDragOverFolder(node.id);
        }}
        onDragLeave={() => onDragOverFolder(null)}
        onDrop={(event) => {
          const kind = dragKind(Array.from(event.dataTransfer.types));
          onDragOverFolder(null);
          if (kind === "upload") {
            event.preventDefault();
            event.stopPropagation();
            onUploadFiles(Array.from(event.dataTransfer.files), node.id);
            return;
          }
          if (kind === "artifact") {
            event.preventDefault();
            event.stopPropagation();
            const artifactId = droppedArtifactId(event.dataTransfer);
            if (artifactId) void onMoveItems([artifactId], node.id);
            return;
          }
          if (kind === "folder") {
            event.preventDefault();
            event.stopPropagation();
            const folderId = event.dataTransfer.getData(MIME_LIBRARY_FOLDER_ID);
            if (folderId && folderId !== node.id) {
              void onMoveFolder(folderId, node.id);
            }
          }
        }}
      />
      {open ? (
        <div
          role="group"
          aria-label={`${node.name} contents`}
          {...stylex.props(s.files)}
        >
          {node.nodes.map((child) => (
            <LibraryRow
              key={child.key}
              node={child}
              workspaceId={workspaceId}
              collapsedFolders={collapsedFolders}
              filtering={filtering}
              tabbableKey={tabbableKey}
              selectedId={selectedId}
              renamingFolderId={renamingFolderId}
              dragOverFolderId={dragOverFolderId}
              renameInputRef={renameInputRef}
              onToggle={onToggle}
              onFocusRow={onFocusRow}
              onSelect={onSelect}
              onStartRename={onStartRename}
              onEndRename={onEndRename}
              onRename={onRename}
              onCreateSubfolder={onCreateSubfolder}
              onDelete={onDelete}
              onDragOverFolder={onDragOverFolder}
              onMoveFolder={onMoveFolder}
              onMoveItems={onMoveItems}
              onUploadFiles={onUploadFiles}
            />
          ))}
        </div>
      ) : null}
    </>
  );
}
