import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@public-profile-search/generated-api-client"],
};

export default nextConfig;

