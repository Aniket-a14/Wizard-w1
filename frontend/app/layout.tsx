import type { Metadata, Viewport } from "next"
import type React from "react"

import "./globals.css"

export const metadata: Metadata = {
  title: "Wizard — Local-first data analysis agent",
  description:
    "Ask a question, watch it think. Wizard plans the analysis, writes the Python, runs it in a sandbox and explains the result — on your machine, with your models.",
  // Only the icon that actually exists in /public is declared; the previous
  // manifest pointed at four files that were never added, so every page load
  // issued 404s for them.
  icons: { icon: "/favicon.ico" },
  openGraph: {
    title: "Wizard — Local-first data analysis agent",
    description: "Plans the analysis, writes the Python, runs it in a sandbox, explains the result.",
    type: "website",
  },
}

export const viewport: Viewport = {
  // Light only: one committed look, so the browser chrome is told exactly one
  // colour rather than being handed a scheme it can second-guess.
  themeColor: "#fdfcfb",
  colorScheme: "light",
  width: "device-width",
  initialScale: 1,
  // maximumScale/userScalable were pinned, which blocks pinch-zoom and fails
  // WCAG 1.4.4. Users need to be able to zoom a data table.
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        {/* Ambient wash. Fixed and inert, behind every route. */}
        <div className="aurora" aria-hidden="true" />
        {children}
      </body>
    </html>
  )
}
