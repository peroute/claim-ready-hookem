import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Claim-ready — Turn your damage video into a claim packet",
  description:
    "AI-generated inventory, policy citations, and FNOL letter — ready to send in under 3 minutes.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen bg-app-gradient font-sans antialiased text-slate-900">
        {children}
      </body>
    </html>
  );
}
