export type FileStatus = "uploading" | "ready" | "failed" | "deleting";

export type FileItem = {
  id: string;
  name: string;
  size: number;
  mime_type: string;
  extension: string;
  status: FileStatus;
  created_at: string;
  updated_at: string;
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
] as const;

/** Keep in sync with MAX_FILE_SIZE_BYTES on the backend (default 100MB). */
export const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024;
