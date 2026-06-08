"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/theme-toggle";

type Module = { key: string; name: string; description: string; enabled: boolean };

export function Sidebar({
  name,
  tagline,
  modules,
}: {
  name: string;
  tagline?: string;
  modules: Module[];
}) {
  const pathname = usePathname();
  const items = modules
    .filter((m) => m.enabled)
    .map((m) => ({ key: m.key, name: m.name, href: `/${m.key}` }));

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface px-4 py-6">
      <div className="mb-8 px-2">
        <div className="text-lg font-semibold tracking-tight text-fg">{name}</div>
        {tagline && <div className="text-xs text-muted">{tagline}</div>}
      </div>
      <nav className="flex-1 space-y-1 text-sm">
        {items.map((it) => {
          const active = pathname === it.href || pathname.startsWith(`${it.href}/`);
          return (
            <Link
              key={it.key}
              href={it.href}
              className={[
                "block rounded-md px-3 py-2 transition",
                active
                  ? "bg-fg/10 font-medium text-fg"
                  : "text-muted hover:bg-fg/5 hover:text-fg",
              ].join(" ")}
            >
              {it.name}
            </Link>
          );
        })}
      </nav>
      <div className="mt-4">
        <ThemeToggle />
      </div>
    </aside>
  );
}
