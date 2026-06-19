"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { SUBNAV_PROVIDERS, type SubItem } from "@/lib/nav";
import { ThemeToggle } from "@/components/theme-toggle";
import { ApiStatus } from "@/components/api-status";

type Module = { key: string; name: string; description: string; enabled: boolean };

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

// Collapse/expand the whole rail: a panel glyph with a chevron pointing the way it will go.
function CollapseIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.5}>
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
      <path d="M6 2.5v11" strokeLinecap="round" />
      <path
        d={collapsed ? "M9.5 6l2 2-2 2" : "M11.5 6l-2 2 2 2"}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// Whole-rail collapse lives in localStorage and is read via useSyncExternalStore (like the theme)
// — no set-state-in-effect, and a stable server snapshot (expanded) so hydration never mismatches.
const COLLAPSE_KEY = "qrp-sidebar-collapsed";
const collapseListeners = new Set<() => void>();
function subscribeCollapse(cb: () => void): () => void {
  collapseListeners.add(cb);
  window.addEventListener("storage", cb); // cross-tab
  return () => {
    collapseListeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}
function getCollapseSnapshot(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}
function getCollapseServerSnapshot(): boolean {
  return false;
}
function setCollapsedStored(next: boolean): void {
  try {
    localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
    collapseListeners.forEach((l) => l()); // notify this tab (storage event is cross-tab only)
  } catch {
    /* ignore */
  }
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

  // Async submenus (e.g. macro categories) are data-driven, so they can never drift from the
  // data. Resolved per module via the registry's `fetch` providers, with a fail-safe: a failed
  // or late fetch never wipes a WORKING submenu, and an empty submenu retries on any route
  // change so one cold-start failure can't hide it for the whole session. This is generic over
  // ANY fetch-kind provider — no module name is hardcoded (NFR-10).
  const [fetched, setFetched] = useState<Record<string, SubItem[]>>({});
  const fetchedRef = useRef<Record<string, SubItem[]>>({});
  const loadedOkRef = useRef<Set<string>>(new Set());
  const asyncKeysSig = items
    .filter((it) => SUBNAV_PROVIDERS[it.key]?.kind === "fetch")
    .map((it) => it.key)
    .join(",");
  const loadSub = useCallback((key: string) => {
    const p = SUBNAV_PROVIDERS[key];
    if (!p || p.kind !== "fetch") return;
    p.load()
      .then((sub) => {
        loadedOkRef.current.add(key); // a successful load (even of an empty list) is not retried
        fetchedRef.current = { ...fetchedRef.current, [key]: sub };
        setFetched((f) => ({ ...f, [key]: sub }));
      })
      .catch(() => {
        // a late/stale failure (e.g. a cold-start fetch losing a race to a successful retry)
        // must never wipe a WORKING submenu; leaving the key un-"loaded" lets it retry
        if ((fetchedRef.current[key] ?? []).length === 0) {
          setFetched((f) => ({ ...f, [key]: [] }));
        }
      });
  }, []);
  useEffect(() => {
    // load each async submenu once; only a FAILED load retries on a later route change (so a
    // cold-start failure can't hide it for the session) — a successful-but-empty result does
    // NOT re-fetch every navigation.
    for (const key of asyncKeysSig ? asyncKeysSig.split(",") : []) {
      if (!loadedOkRef.current.has(key)) loadSub(key);
    }
  }, [asyncKeysSig, pathname, loadSub]);

  // Expand/collapse is DECOUPLED from navigation (operator change request): the chevron
  // toggles a submenu in place; the module label navigates; the active module defaults
  // to expanded until the user says otherwise.
  const [open, setOpen] = useState<Record<string, boolean>>({});

  // Whole-rail collapse, persisted in localStorage (see the external store above).
  const collapsed = useSyncExternalStore(subscribeCollapse, getCollapseSnapshot, getCollapseServerSnapshot);
  const toggleCollapsed = useCallback(() => setCollapsedStored(!getCollapseSnapshot()), []);

  const subnavFor = (key: string): SubItem[] => {
    const p = SUBNAV_PROVIDERS[key];
    if (!p) return [];
    return p.kind === "static" ? p.items : (fetched[key] ?? []);
  };

  return (
    <aside
      className={[
        "flex shrink-0 flex-col border-r border-border bg-surface py-6 transition-[width] duration-200 ease-out",
        collapsed ? "w-16 px-2" : "w-60 px-4",
      ].join(" ")}
    >
      <div className={collapsed ? "mb-6 flex flex-col items-center gap-3" : "mb-8 px-2"}>
        {collapsed ? (
          <>
            <button
              type="button"
              onClick={toggleCollapsed}
              aria-label="Expand sidebar"
              title="Expand sidebar"
              className="rounded-md p-2 text-muted hover:bg-fg/5 hover:text-fg"
            >
              <CollapseIcon collapsed />
            </button>
            <ApiStatus />
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <div className="text-lg font-semibold tracking-tight text-fg">{name}</div>
              <ApiStatus />
              <button
                type="button"
                onClick={toggleCollapsed}
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
                className="ml-auto rounded-md p-1.5 text-muted hover:bg-fg/5 hover:text-fg"
              >
                <CollapseIcon collapsed={false} />
              </button>
            </div>
            {tagline && <div className="text-xs text-muted">{tagline}</div>}
          </>
        )}
      </div>

      {collapsed ? (
        // Collapsed rail: module links as single-letter buttons (full name on hover); submenus
        // and the theme control are only available expanded.
        <nav className="flex-1 space-y-1">
          {items.map((it) => {
            const active = pathname === it.href || pathname.startsWith(`${it.href}/`);
            return (
              <Link
                key={it.key}
                href={it.href}
                title={it.name}
                aria-label={it.name}
                className={[
                  "flex h-9 items-center justify-center rounded-md text-sm font-medium uppercase transition",
                  active ? "bg-fg/10 text-fg" : "text-muted hover:bg-fg/5 hover:text-fg",
                ].join(" ")}
              >
                {it.name.slice(0, 2)}
              </Link>
            );
          })}
        </nav>
      ) : (
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
      )}
      {!collapsed && (
        <div className="mt-4">
          <ThemeToggle />
        </div>
      )}
    </aside>
  );
}
