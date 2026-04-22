import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cloud File Sync",
  description: "Secure private file storage and sync.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
