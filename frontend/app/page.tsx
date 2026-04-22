export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold">Cloud File Sync</h1>
      <p className="text-sm opacity-70">
        Scaffold is up. Auth & dashboard coming in M1/M4.
      </p>
      <a
        href="/api/health"
        className="text-sm underline opacity-80 hover:opacity-100"
      >
        /api/health
      </a>
    </main>
  );
}
