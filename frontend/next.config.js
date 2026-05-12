/** @type {import('next').NextConfig} */
const apiTarget = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8003';

module.exports = {
  allowedDevOrigins: ['100.88.49.58'],
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${apiTarget}/api/:path*` },
      { source: '/ws/:path*', destination: `${apiTarget}/ws/:path*` },
    ];
  },
};
