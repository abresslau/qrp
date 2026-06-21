"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { MONITOR_SUBNAV } from "@/lib/nav";

// Monitor — the top-level area for at-a-glance market boards (World equity indices, Heat map,
// Portfolio live). Mirrors the sym layout's tab strip so the two areas feel consistent.
export default function MonitorLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    // pull up into the app shell's main py-4 so the tab strip sits close to the top (less dead space
    // above the tabs); a touch more breathing room on tall screens.
    <div className="-mt-2 w-full [@media(min-height:960px)]:mt-0">
      <div className="mb-2 flex gap-1 border-b border-border [@media(min-height:960px)]:mb-4">
        {MONITOR_SUBNAV.map((t) => {
          const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
          return (
            <Link
              key={t.href}
              href={t.href}
              className={[
                "-mb-px border-b-2 px-3 py-1.5 text-sm transition [@media(min-height:960px)]:py-2",
                active
                  ? "border-fg font-medium text-fg"
                  : "border-transparent text-muted hover:text-fg",
              ].join(" ")}
            >
              {t.label}
            </Link>
          );
        })}
      </div>
      {children}
    </div>
  );
}
