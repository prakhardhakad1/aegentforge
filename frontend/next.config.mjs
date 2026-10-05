/** @type {import('next').NextConfig} */

// Read the API base from NEXT_PUBLIC_API_BASE_URL (inlined at build time by Next.js).
// Default: the pinned local backend at http://localhost:8000.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,

  async rewrites() {
    // Proxy /api/:path* to the FastAPI backend so the browser can use
    // same-origin /api/... URLs (avoids CORS in dev when CORS_ORIGINS is
    // narrow) while lib/api.ts can still target the backend directly.
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
