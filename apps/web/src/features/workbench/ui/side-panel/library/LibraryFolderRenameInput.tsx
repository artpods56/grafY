"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { panelStyles as s } from "../panel-styles";

/**
 * An uncontrolled rename box that commits exactly once, whether it closes on
 * Enter, a click away, or Escape. It mounts only while its folder is renaming.
 */
export function LibraryFolderRenameInput({
  initialName,
  inputRef,
  onCommit,
  onCancel,
}: {
  initialName: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onCommit: (name: string) => void;
  onCancel: () => void;
}) {
  const settled = React.useRef(false);

  function commit(value: string): void {
    if (settled.current) return;
    settled.current = true;
    onCommit(value);
  }

  return (
    <input
      ref={inputRef}
      aria-label="Folder name"
      defaultValue={initialName}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          commit(event.currentTarget.value);
        }
        if (event.key === "Escape") {
          event.preventDefault();
          settled.current = true;
          onCancel();
        }
      }}
      onBlur={(event) => commit(event.currentTarget.value)}
      {...stylex.props(s.renameInput)}
    />
  );
}
