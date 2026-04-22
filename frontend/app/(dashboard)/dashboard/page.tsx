"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { authApi } from "@/features/auth/api";
import { useAuthStore } from "@/features/auth/store";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function DashboardPage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      clear();
      toast.success("Signed out.");
      router.replace("/login");
    },
    onError: () => {
      // Logout is best-effort; clear local state regardless.
      clear();
      router.replace("/login");
    },
  });

  if (!user) return null;

  const usagePct = user.storage_quota
    ? Math.round((user.storage_used / user.storage_quota) * 100)
    : 0;

  return (
    <div className="mx-auto max-w-5xl p-6">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-neutral-500">
            Signed in as <span className="font-medium">{user.email}</span>
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => logoutMutation.mutate()}
          disabled={logoutMutation.isPending}
        >
          {logoutMutation.isPending ? "Signing out…" : "Sign out"}
        </Button>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Storage</CardTitle>
            <CardDescription>Your usage across Backblaze B2.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>{formatBytes(user.storage_used)} used</span>
                <span className="text-neutral-500">
                  of {formatBytes(user.storage_quota)}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-neutral-200">
                <div
                  className="h-full bg-black transition-all"
                  style={{ width: `${Math.min(usagePct, 100)}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Files</CardTitle>
            <CardDescription>Upload, preview, and sync coming in M2–M4.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-neutral-500">
              Auth is live. File management ships next milestone.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
