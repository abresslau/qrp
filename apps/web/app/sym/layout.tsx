"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/sym", label: "Overview" },
  { href: "/sym/explorer", label: "Explorer" },
  { href: "/sym/universes", label: "Universes" },
  { href: "/sym/heatmap", label: "Heat map" },
  { href: "/sym/attention", label: "Attention" },
  { href: "/sym/validation", label: "Validation" },
  { href: "/sym/operate", label: "Operate" },
];

export default function SymLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex gap-1 border-b border-border">
        {tabs.map((t) => {
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
