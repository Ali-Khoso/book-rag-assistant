import type { Metadata } from "next";
import type { ReactNode } from "react";
import { connection } from 'next/server';
import "./globals.css";

export const metadata: Metadata = {
  title: "Bookwise — Ask your books",
  description: "A private, source-cited assistant for your books and learning documents.",
};

export default async function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  // Per-request CSP nonces require dynamic HTML rather than a reused static page.
  await connection();
  return <html lang="en" data-scroll-behavior="smooth"><body>{children}</body></html>;
}
