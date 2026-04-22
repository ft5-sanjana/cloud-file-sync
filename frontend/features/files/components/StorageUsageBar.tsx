"use client";

import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useStorageUsage } from "../hooks";
import { formatBytes } from "../utils";

export function StorageUsageBar({ className }: { className?: string }) {
  const { data, isLoading, isError } = useStorageUsage();

  if (isLoading) {
    return (
      <div className={cn("space-y-2", className)}>
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-2 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className={cn("text-sm text-neutral-500", className)}>
        Storage usage unavailable.
      </div>
    );
  }

  const pct = data.quota > 0 ? Math.round((data.used / data.quota) * 100) : 0;
  const near = pct >= 90;

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{formatBytes(data.used)} used</span>
        <span className="text-neutral-500">
          of {formatBytes(data.quota)} · {data.file_count} file{data.file_count === 1 ? "" : "s"}
        </span>
      </div>
      <Progress value={pct} />
      {near ? (
        <p className="text-xs text-red-600">You&apos;re near your storage limit.</p>
      ) : null}
    </div>
  );
}
