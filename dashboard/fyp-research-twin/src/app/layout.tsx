import type { Metadata } from "next";
import "./globals.css";

// System fonts only, so the dashboard builds and runs without internet access.

export const metadata: Metadata = {
  title: "Smart Building Digital Twin",
  description: "Live view of the edge brain: Office A from the ESP32 board, 25 simulated rooms",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
