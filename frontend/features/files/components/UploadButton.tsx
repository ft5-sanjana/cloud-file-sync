"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

import { useUploadFile } from "../hooks";
import { ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES } from "../types";
import { formatBytes } from "../utils";

const ACCEPT = ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",");

function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i >= 0 ? filename.slice(i + 1).toLowerCase() : "";
}

export function UploadButton() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [currentName, setCurrentName] = useState<string | null>(null);
  const upload = useUploadFile();

  const handlePick = () => inputRef.current?.click();

  const handleFile = async (file: File) => {
    const ext = extOf(file.name);
    if (!ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
      toast.error(`Unsupported file type: .${ext || "unknown"}`);
      return;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      toast.error(`File too large. Max ${formatBytes(MAX_FILE_SIZE_BYTES)}.`);
      return;
    }

    setCurrentName(file.name);
    setProgress(0);
    try {
      await upload.mutateAsync({
        file,
        onProgress: (p) => setProgress(p.percent),
      });
    } finally {
      setProgress(null);
      setCurrentName(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void handleFile(file);
  };

  const uploading = progress !== null;

  return (
    <div className="flex flex-col items-end gap-2">
      <Button onClick={handlePick} disabled={uploading}>
        <Upload className="mr-2 h-4 w-4" />
        {uploading ? "Uploading…" : "Upload file"}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        onChange={onChange}
        className="hidden"
        aria-hidden
      />
      {uploading ? (
        <div className="w-56 space-y-1">
          <div className="flex justify-between text-xs text-neutral-600">
            <span className="truncate">{currentName}</span>
            <span>{progress}%</span>
          </div>
          <Progress value={progress ?? 0} />
        </div>
      ) : null}
    </div>
  );
}
