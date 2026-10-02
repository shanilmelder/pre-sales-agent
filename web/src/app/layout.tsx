import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { cn } from "cn";

import { ThemeScript } from "@/components/theme-script";
import { getPreferences, htmlPreferenceAttributes } from "@/lib/preferences";

import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Pre-Sales Agent",
  description: "Agentic AI Presales Platform",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const { className, ...preferenceAttributes } = htmlPreferenceAttributes(
    await getPreferences(),
  );
  return (
    <html
      lang="en"
      {...preferenceAttributes}
      className={cn(inter.variable, jetbrainsMono.variable, "h-full antialiased", className)}
      // The theme script may add `.dark` before hydration when the theme is System.
      suppressHydrationWarning
    >
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
