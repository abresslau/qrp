import type { NextConfig } from "next";

// Same-origin proxy: browser/client calls to /api/* forward to the FastAPI service.
// (Server Components fetch the API directly via API_BASE — see lib/api.ts.)
const API = process.env.API_BASE ?? "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
