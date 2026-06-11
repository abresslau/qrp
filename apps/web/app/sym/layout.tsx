"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SYM_SUBNAV } from "@/lib/nav";

export default function SymLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex gap-1 border-b border-border">
        {SYM_SUBNAV.map((t) => {
          const active = pathname === t.href;
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
