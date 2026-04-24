export type FileStatus = "uploading" | "ready" | "failed" | "deleting";

export type FileItem = {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  extension: string;
  status: FileStatus;
  /** Parent folder id, or null if the file sits at the root. */
  folder_id: string | null;
  created_at: string;
  updated_at: string;
};

export type FolderItem = {
  id: string;
  name: string;
  /** Materialized path including the folder's own name (no leading slash). */
  path: string;
  parent_id: string | null;
  /** Direct file/subfolder counts — one level, not subtree totals. */
  file_count: number;
  subfolder_count: number;
  created_at: string;
  updated_at: string;
};

export type FolderListResponse = {
  items: FolderItem[];
};

export type FolderDeleteResult = {
  folders_deleted: number;
  files_deleted: number;
  versions_purged: number;
};

export type FolderDownloadUrlResponse = {
  url: string;
  expires_at: string;
  filename: string;
};

export type FileListResponse = {
  items: FileItem[];
  total: number;
  page: number;
  page_size: number;
};

export type SignedUrlMode = "preview" | "download";

export type SignedUrlResponse = {
  url: string;
  expires_at: string;
  mode: SignedUrlMode;
};

export type StorageUsage = {
  used: number;
  quota: number;
  file_count: number;
};

/** Extensions supported by the backend — used for client-side pre-validation. */
export const ALLOWED_EXTENSIONS = [
  "doc", "docx", "pdf", "xls", "xlsx", "ppt", "pptx",
  "png", "jpeg", "jpg", "svg", "txt",
  "odt", "zip",
] as const;

/** Keep in sync with MAX_FILE_SIZE_BYTES on the backend (default 100MB). */
export const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024;
