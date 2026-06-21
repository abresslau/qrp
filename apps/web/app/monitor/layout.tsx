"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { MONITOR_SUBNAV } from "@/lib/nav";

// Monitor — the top-level area for at-a-glance market boards (World equity indices, Heat map,
// Portfolio live). Mirrors the sym layout's tab strip so the two areas feel consistent.
export default function MonitorLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    // Fill the viewport height (minus the app shell's py-4) as a flex column: the tab strip is fixed,
    // and children get the remaining height in a scroll-safe flex-1 region. This lets a page opt to
    // STRETCH to fill (h-full) so large screens don't leave dead space below the content. The -mt-2
    // pulls the strip up into the shell padding so there's little dead space above the tabs.
    <div className="-mt-3.5 flex h-[calc(100dvh-2rem)] w-full flex-col [@media(min-height:960px)]:-mt-2">
      <div className="mb-2 flex shrink-0 gap-1 border-b border-border [@media(min-height:960px)]:mb-4">
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
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  );
}
