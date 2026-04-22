/**
 * Pure helpers for the files feature — no React, no network.
 */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / Math.pow(1024, i);
  const precision = value < 10 && i > 0 ? 1 : 0;
  return `${value.toFixed(precision)} ${units[i]}`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export type FileKind = "image" | "pdf" | "document" | "spreadsheet" | "presentation" | "text" | "other";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "svg"]);
const DOC_EXTS = new Set(["doc", "docx"]);
const SHEET_EXTS = new Set(["xls", "xlsx"]);
const SLIDE_EXTS = new Set(["ppt", "pptx"]);

export function getFileKind(extension: string): FileKind {
  const ext = extension.toLowerCase();
  if (ext === "pdf") return "pdf";
  if (ext === "txt") return "text";
  if (IMAGE_EXTS.has(ext)) return "image";
  if (DOC_EXTS.has(ext)) return "document";
  if (SHEET_EXTS.has(ext)) return "spreadsheet";
  if (SLIDE_EXTS.has(ext)) return "presentation";
  return "other";
}

export function isPreviewable(extension: string): boolean {
  const k = getFileKind(extension);
  return k === "image" || k === "pdf";
}
