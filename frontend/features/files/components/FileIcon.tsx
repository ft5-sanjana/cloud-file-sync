"use client";

import {
  FileText,
  FileImage,
  FileSpreadsheet,
  FileType2,
  File as FileIconBase,
  Presentation,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { getFileKind, type FileKind } from "../utils";

const ICON_MAP: Record<FileKind, React.ComponentType<{ className?: string }>> = {
  pdf: FileText,
  image: FileImage,
  document: FileType2,
  spreadsheet: FileSpreadsheet,
  presentation: Presentation,
  text: FileText,
  other: FileIconBase,
};

const COLOR_MAP: Record<FileKind, string> = {
  pdf: "text-red-500",
  image: "text-purple-500",
  document: "text-blue-500",
  spreadsheet: "text-green-600",
  presentation: "text-orange-500",
  text: "text-neutral-500",
  other: "text-neutral-500",
};

export function FileIcon({
  extension,
  className,
}: {
  extension: string;
  className?: string;
}) {
  const kind = getFileKind(extension);
  const Icon = ICON_MAP[kind];
  return <Icon className={cn(COLOR_MAP[kind], className)} />;
}
