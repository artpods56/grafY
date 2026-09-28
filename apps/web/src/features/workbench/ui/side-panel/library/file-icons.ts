import {
  Boxes,
  File as FileIcon,
  FileText,
  Image as ImageIcon,
  Table,
  type LucideIcon,
} from "lucide-react";

import type { LibraryFileIcon } from "../library-tree";

export const FILE_ICONS: Record<LibraryFileIcon, LucideIcon> = {
  image: ImageIcon,
  table: Table,
  text: FileText,
  model: Boxes,
  other: FileIcon,
};
