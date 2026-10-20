import type { NextConfig } from "next";
import os from "os";

// In development Next.js only serves its scripts to pages opened as "localhost".
// Allow 127.0.0.1 and this computer's own network addresses too, so the dashboard
// also works when opened from another device on the same Wi-Fi (e.g. the projector
// laptop) as http://<this PC's IP>:3000. Extra hosts: NEXT_ALLOWED_DEV_ORIGINS=a,b
const lanAddresses = Object.values(os.networkInterfaces())
  .flat()
  .filter((a): a is os.NetworkInterfaceInfo => !!a && a.family === "IPv4")
  .map((a) => a.address);

const extra = (process.env.NEXT_ALLOWED_DEV_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);

const nextConfig: NextConfig = {
  allowedDevOrigins: Array.from(new Set(["127.0.0.1", "localhost", ...lanAddresses, ...extra])),
  // no floating Next.js badge over the 3D view during presentations (errors are still shown)
  devIndicators: false,
};

export default nextConfig;
