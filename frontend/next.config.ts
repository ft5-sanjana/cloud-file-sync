import type { NextConfig } from "next";

const API_UPSTREAM = process.env.API_UPSTREAM_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",

  // Same-origin proxy in dev: browser hits /api/* on :3000, Next.js forwards
  // to the Django container. This lets the refresh_token HttpOnly cookie
  // flow naturally with SameSite=Lax — no cross-origin credentials mess.
  async rewrites() {
    return {
      // `afterFiles` runs after Next.js filesystem routes, so local handlers
      // like /api/health still work; everything else under /api/* proxies to Django.
      afterFiles: [
        {
          source: "/api/:path*",
          destination: `${API_UPSTREAM}/api/:path*`,
        },
      ],
      beforeFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;
