import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "192.168.1.45"],
  output: "standalone",
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
