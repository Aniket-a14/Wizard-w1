import { Outfit, DM_Sans } from "next/font/google";
import "./globals.css";

const outfit = Outfit({ 
  subsets: ["latin"], 
  variable: "--font-outfit",
  display: "swap",
});

const dmSans = DM_Sans({ 
  subsets: ["latin"], 
  variable: "--font-dm-sans",
  display: "swap",
});

export const metadata = {
  title: "Wizard AI | Level 100 Analytics",
  description: "Autonomous Data Science Agent powered by Advanced Reasoning",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${outfit.variable} ${dmSans.variable}`}>
      <body className="font-sans antialiased bg-slate-950 text-slate-100 overflow-x-hidden selection:bg-indigo-500/30">
        {children}
      </body>
    </html>
  );
}
