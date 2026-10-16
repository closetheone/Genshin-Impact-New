import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "webstatic.mihoyo.com" },
      { protocol: "https", hostname: "uploadstatic.mihoyo.com" },
    ],
  },
  async rewrites() {
    return [{
      source: "/api/:path*",
      destination: `${process.env.PYTHON_API_URL || "http://127.0.0.1:4175"}/api/:path*`,
    }];
  },
};

export default nextConfig;
