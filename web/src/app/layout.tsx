import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { cn } from "cn";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ShellProviders } from "@/components/shell/shell-context";
import { ThemeScript } from "@/components/theme-script";
import { getPreferences, hasStoredPreferences, htmlPreferenceAttributes } from "@/lib/preferences";

import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Pre Sales Agent Framework",
  description: "Agentic AI Presales Platform",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const preferences = await getPreferences();
  const firstRun = !(await hasStoredPreferences());
  const { className, ...preferenceAttributes } = htmlPreferenceAttributes(preferences);
  return (
    <html
      lang="en"
      {...preferenceAttributes}
      className={cn(inter.variable, "h-full antialiased", className)}
      // The theme script may add `.dark` before hydration when the theme is System.
      suppressHydrationWarning
    >
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-full flex flex-col">
        {/* State only (sidebar, right pane, live region): pages still gate their content. */}
        <TooltipProvider>
          <ShellProviders
            singleKeyShortcuts={preferences.singleKeyShortcuts}
            firstRun={firstRun}
            theme={preferences.theme}
            density={preferences.density}
          >
            {children}
          </ShellProviders>
        </TooltipProvider>
      </body>
    </html>
  );
}
