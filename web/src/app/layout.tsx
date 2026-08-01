import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Bitemporal",
  description: "Equity analysis for Indian, US and UK markets",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
