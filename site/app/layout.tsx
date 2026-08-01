import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import { SmoothScroll } from "./providers";
import "./globals.css";

const siteUrl = "https://lucas-bianco.github.io/pokemon-card-platform/";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Pokémon Card Platform",
  description:
    "Point a camera. Know the card. A premium Pokémon card grading and valuation platform — scan, grade, and track your collection in real time.",
  openGraph: {
    title: "Pokémon Card Platform",
    description:
      "Point a camera. Know the card. Scan, grade, and track your Pokémon card collection.",
    url: siteUrl,
    siteName: "Pokémon Card Platform",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Pokémon Card Platform",
    description: "Point a camera. Know the card.",
  },
};

export const viewport: Viewport = {
  themeColor: "#0b0d12",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <SmoothScroll>{children}</SmoothScroll>
      </body>
    </html>
  );
}