import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: { position: "top-right" },
  allowedDevOrigins: ["127.0.0.1", "192.168.1.45"],
  output: "standalone",
  // The dev rewrite below buffers proxied request bodies and truncates them at
  // 10 MB by default, which breaks API-owned uploads. Match the nginx gateway
  // (65m) so the dev proxy accepts everything the API's 64 MiB cap does.
  experimental: { proxyClientMaxBodySize: "65mb" },
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];

    const apiUpstream =
      process.env.GRAFY_API_UPSTREAM ?? "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUpstream}/:path*`,
      },
    ];
  },
};

export default nextConfig;
