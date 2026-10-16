import type { NextConfig } from "next";

const LOCAL_API_URL = "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The browser reaches the API through the web app's own address, which forwards /api to the
  // API's own address.
  async rewrites() {
    const apiUrl = process.env.API_URL ?? LOCAL_API_URL;
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
