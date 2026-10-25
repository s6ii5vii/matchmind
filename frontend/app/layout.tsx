import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "MatchMind · Hear the take. See the data.",
  description: "Five AI agents watch a fictional football match: a Pundit says what everyone's thinking, a Skeptic checks it against the data. Built for the Microsoft Premier League Hackathon 2026.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}