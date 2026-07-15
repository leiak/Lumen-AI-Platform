/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{
      source: "/api/v1/:path*",
      destination: "http://127.0.0.1:11335/api/v1/:path*",
    }];
  },
};
module.exports = nextConfig;
