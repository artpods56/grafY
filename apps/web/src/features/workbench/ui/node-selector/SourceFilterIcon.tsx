"use client";

import * as React from "react";
import { LayoutGrid, LibraryBig, Package } from "lucide-react";

import type { CatalogFilter } from "../../model/node-catalog";

export function SourceFilterIcon({ filter }: { filter: CatalogFilter }) {
  if (filter.id === "all") return <LayoutGrid size={14} />;
  if (filter.id === "workspace-library") return <LibraryBig size={14} />;
  return <Package size={14} />;
}
