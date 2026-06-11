"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { STATIC_SUBNAV, type SubItem } from "@/lib/nav";
import { ThemeToggle } from "@/components/theme-toggle";
import type { Schemas } from "@/lib/api";

type Module = { key: string; name: string; description: string; enabled: boolean };
type CategorySummary = Schemas["CategorySummary"];

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`h-3.5 w-3.5 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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

  // macro's submenu is data-driven: categories live in the macro DB, so the submenu can
  // never drift from the data. A failed fetch shows NO submenu (never an error-as-data);
  // navigating into /macro retries an empty list so one cold-start failure doesn't hide
  // the submenu for the whole session.
  const [macroSub, setMacroSub] = useState<SubItem[]>([]);
  const macroSubRef = useRef<SubItem[]>([]);
  const macroEnabled = modules.some((m) => m.key === "macro" && m.enabled);
  const loadCategories = useCallback(() => {
    fetch("/api/macro/categories", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((cats: CategorySummary[]) => {
        const sub = cats.map((c) => ({
          href: `/macro/${encodeURIComponent(c.category)}`,
          label: c.category,
          badge: c.n_series,
        }));
        macroSubRef.current = sub;
        setMacroSub(sub);
      })
      .catch(() => {
        // a late/stale failure (e.g. the cold-start fetch losing a race to a successful
        // retry) must never wipe a WORKING submenu
        if (macroSubRef.current.length === 0) setMacroSub([]);
      });
  }, []);
  useEffect(() => {
    // retry an empty list on ANY route change (cheap no-op once populated) — a single
    // cold-start failure must not hide the submenu for the session
    if (macroEnabled && macroSubRef.current.length === 0) loadCategories();
  }, [macroEnabled, pathname, loadCategories]);

  // Expand/collapse is DECOUPLED from navigation (operator change request): the chevron
  // toggles a submenu in place; the module label navigates; the active module defaults
  // to expanded until the user says otherwise.
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const subnavFor = (key: string): SubItem[] =>
    key === "macro" ? macroSub : (STATIC_SUBNAV[key] ?? []);

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface px-4 py-6">
      <div className="mb-8 px-2">
        <div className="text-lg font-semibold tracking-tight text-fg">{name}</div>
        {tagline && <div className="text-xs text-muted">{tagline}</div>}
      </div>
      <nav className="flex-1 space-y-1 text-sm">
        {items.map((it) => {
          const active = pathname === it.href || pathname.startsWith(`${it.href}/`);
          const sub = subnavFor(it.key);
          const expanded = sub.length > 0 && (open[it.key] ?? active);
          return (
            <div key={it.key}>
              <div
                className={[
                  "flex items-center rounded-md transition",
                  active ? "bg-fg/10 font-medium text-fg" : "text-muted hover:bg-fg/5 hover:text-fg",
                ].join(" ")}
              >
                <Link href={it.href} className="flex-1 px-3 py-2">
                  {it.name}
                </Link>
                {sub.length > 0 && (
                  <button
                    type="button"
                    aria-label={`${expanded ? "Collapse" : "Expand"} ${it.name}`}
                    aria-expanded={expanded}
                    onClick={() =>
                      setOpen((o) => ({ ...o, [it.key]: !(o[it.key] ?? active) }))
                    }
                    className="px-2 py-2 text-muted hover:text-fg"
                  >
                    <Chevron open={expanded} />
                  </button>
                )}
              </div>
              {sub.length > 0 && (
                // Minimal open-down animation: the grid-rows 0fr->1fr transition animates
                // to the content's natural height (no max-height magic numbers).
                <div
                  className={[
                    "grid transition-[grid-template-rows] duration-200 ease-out",
                    expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
                  ].join(" ")}
                >
                  <div className="overflow-hidden">
                    <div className="ml-3 mt-1 space-y-0.5 border-l border-border pb-1 pl-2">
                      {sub.map((s) => {
                        const subActive = pathname === s.href;
                        return (
                          <Link
                            key={s.href}
                            href={s.href}
                            className={[
                              "flex items-center justify-between rounded-md px-2 py-1 text-xs transition",
                              subActive
                                ? "bg-fg/10 font-medium text-fg"
                                : "text-muted hover:bg-fg/5 hover:text-fg",
                            ].join(" ")}
                          >
                            <span>{s.label}</span>
                            {s.badge !== undefined && (
                              <span className="tabular-nums text-muted">{s.badge}</span>
                            )}
                          </Link>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <div className="mt-4">
        <ThemeToggle />
      </div>
    </aside>
  );
}
