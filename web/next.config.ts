import type { NextConfig } from "next";

import { UPLOAD_BODY_LIMIT_BYTES } from "./src/lib/upload-limits";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image.
  output: "standalone",
  experimental: {
    // Source uploads go through a Server Action (default limit 1 MB) after proxy.ts, which
    // buffers a copy of every body (default 10 MB, and silently truncated past it). Both
    // must carry a 50 MB file plus its multipart framing; the API enforces the real limit.
    serverActions: { bodySizeLimit: UPLOAD_BODY_LIMIT_BYTES },
    proxyClientMaxBodySize: UPLOAD_BODY_LIMIT_BYTES,
  },
};

export default nextConfig;
