import type { NextConfig } from "next";

// STATIC_EXPORT=1 builds plain files that the backend serves itself (one container, one URL).
// Otherwise (npm run dev) the dev server forwards /api to the backend.
const staticExport = process.env.STATIC_EXPORT === "1";

const nextConfig: NextConfig = staticExport
  ? { output: "export" }
  : {
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/api/:path*` }];
      },
    };

export default nextConfig;
