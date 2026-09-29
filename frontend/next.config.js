/** @type {import('next').NextConfig} */
// 2026-09-29 �?API_PROXY_TARGET 支持:docker �?dev �?容器�?127.0.0.1
// 不是 host 上的 backend(backend 跑在另一�?docker 容器),需要走
// host.docker.internal(host gateway)。host dev 不设 env 时仍是默�?
// 127.0.0.1:11335,行为不变�?
const API_PROXY = process.env.API_PROXY_TARGET || 'http://127.0.0.1:11335';

const nextConfig = {
  reactStrictMode: false,
  // SWC-level tree-shake for these heavy libs �?much faster than
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
        destination: `${API_PROXY}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
