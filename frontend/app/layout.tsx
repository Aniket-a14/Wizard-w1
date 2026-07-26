import type { Metadata, Viewport } from "next"
import type React from "react"

import "./globals.css"

export const metadata: Metadata = {
  title: "Wizard — Data Analysis Agent",
  description:
    "Local-first autonomous data analysis. Plans the analysis, writes Python, runs it in a sandbox and explains the result.",
  // Only the icon that actually exists in /public is declared; the previous
  // manifest pointed at four files that were never added, so every page load
  // issued 404s for them.
  icons: { icon: "/favicon.ico" },
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
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
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          Applies the stored or system theme before first paint so dark-mode
          users never see a white flash. Inline by necessity: it has to run
          before React hydrates.
        */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('wizard.theme');" +
              "var d=t?t==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;" +
              "if(d)document.documentElement.classList.add('dark');}catch(e){}})();",
          }}
        />
      </head>
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
