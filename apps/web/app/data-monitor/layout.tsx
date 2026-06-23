"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DATA_MONITOR_SUBNAV } from "@/lib/nav";

// Data Monitor — the data/ETL observability area (pipeline freshness + runs). Mirrors the Monitor
// / sym tab strip so the areas feel consistent.
export default function DataMonitorLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="-mt-3.5 flex h-[calc(100dvh-2rem)] w-full flex-col [@media(min-height:960px)]:-mt-2">
      <div className="mb-2 flex shrink-0 gap-1 border-b border-border [@media(min-height:960px)]:mb-4">
        {DATA_MONITOR_SUBNAV.map((t) => {
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
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
    </div>
  );
}
