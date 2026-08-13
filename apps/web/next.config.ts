import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@public-profile-search/generated-api-client"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8800/:path*",
      },
    ];
  },
};

export default nextConfig;
