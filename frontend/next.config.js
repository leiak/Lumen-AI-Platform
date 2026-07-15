/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  // SWC-level tree-shake for these heavy libs — much faster than
  // `transpilePackages: ['antd', ...]` which forces Babel re-compile on
  // every request and OOMs the dev process. (See CLAUDE.md dev workflow.)
  experimental: {
    optimizePackageImports: [
      'antd',
      '@ant-design/icons',
      '@ant-design/pro-components',
      '@xyflow/react',
      'dayjs',
      'lodash',
    ],
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:11335/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
