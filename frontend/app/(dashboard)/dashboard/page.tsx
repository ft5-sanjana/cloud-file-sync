"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { authApi } from "@/features/auth/api";
import { useAuthStore } from "@/features/auth/store";
import { FileList } from "@/features/files/components/FileList";
import { StorageUsageBar } from "@/features/files/components/StorageUsageBar";

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

  return (
    <div className="mx-auto max-w-6xl p-6">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Your files</h1>
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

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Storage</CardTitle>
          <CardDescription>Your usage across Backblaze B2.</CardDescription>
        </CardHeader>
        <CardContent>
          <StorageUsageBar />
        </CardContent>
      </Card>

      <FileList />
    </div>
  );
}
