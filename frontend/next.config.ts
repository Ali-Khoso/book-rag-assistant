import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Vercel uses its Next.js adapter; other hosts use the traced Docker output.
  output: process.env.VERCEL === '1' ? undefined : 'standalone',
  poweredByHeader: false,
};

export default nextConfig;
