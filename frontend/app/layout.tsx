import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MatchMind | Live football intelligence",
  description: "A synthetic football match intelligence demo for Microsoft's Premier League Hackathon.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
