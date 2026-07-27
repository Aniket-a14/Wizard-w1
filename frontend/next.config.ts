import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server with only the files the runtime actually
  // loads, traced from the build. The Docker image copies that instead of the
  // full node_modules, which had been carrying the entire build toolchain --
  // typescript, eslint, tailwind, the compiler -- into production.
  output: "standalone",
};

export default nextConfig;
