import "./globals.css";
import type { Metadata } from "next";
import { Sidebar } from "@/components/sidebar";
import { CommandPalette } from "@/components/command-palette";
import { apiGet } from "@/lib/api";

type Module = { key: string; name: string; description: string; enabled: boolean };
type Platform = { name: string; tagline?: string; theme?: string; modules: Module[] };

export const metadata: Metadata = { title: "QRP" };

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let platform: Platform | null = null;
  try {
    platform = await apiGet<Platform>("/api/platform");
  } catch {
    platform = null;
  }
  const name = platform?.name ?? "QRP";
  const defaultTheme = platform?.theme === "light" ? "light" : "dark";

  // No-flash init: set the .dark class before paint, from localStorage (light/dark/system)
  // or the platform default. "system" follows prefers-color-scheme.
  const themeScript = `(function(){try{var t=localStorage.getItem('qrp-theme')||'${defaultTheme}';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);if(d){document.documentElement.classList.add('dark');}}catch(e){if('${defaultTheme}'==='dark'){document.documentElement.classList.add('dark');}}})();`;

  return (
    // suppressHydrationWarning: the no-flash script below sets `class="dark"` on <html> before
    // React hydrates, so the server markup (no class) intentionally differs from the live DOM.
    // This scopes the suppression to <html>'s own attributes only (not its subtree).
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen bg-bg text-fg antialiased">
        <div className="flex min-h-screen">
          <Sidebar name={name} tagline={platform?.tagline} modules={platform?.modules ?? []} />
          <main className="min-w-0 flex-1 px-5 py-4">{children}</main>
        </div>
        <CommandPalette modules={platform?.modules ?? []} />
      </body>
    </html>
  );
}
