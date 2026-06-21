"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { MONITOR_SUBNAV } from "@/lib/nav";

// Monitor — the top-level area for at-a-glance market boards (World equity indices, Heat map,
// Portfolio live). Mirrors the sym layout's tab strip so the two areas feel consistent.
export default function MonitorLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="w-full">
      <div className="mb-6 flex gap-1 border-b border-border">
        {MONITOR_SUBNAV.map((t) => {
          const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
          return (
            <Link
              key={t.href}
              href={t.href}
              className={[
                "-mb-px border-b-2 px-3 py-2 text-sm transition",
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
