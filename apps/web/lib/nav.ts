// Per-module sidebar sub-navigation + the generic submenu-provider registry (Story C.1 → QH.6).
//
// QH.6 generalized C.1's two bespoke providers into one registry keyed by module. A module
// optionally supplies a submenu PROVIDER — either a static page list or an async loader for
// data-driven menus. The sidebar (and the command palette) consume this registry generically:
// neither hardcodes a module name, so adding/removing a module needs no shell edit (NFR-10).

import type { Schemas } from "@/lib/api";

type CategorySummary = Schemas["CategorySummary"];

export type SubItem = { href: string; label: string; badge?: number };

// A module's submenu source: a hand-declared page list, or an async fetch (data-driven, so
// the menu can never drift from the data). A module with NO entry simply has no submenu.
export type SubnavProvider =
  | { kind: "static"; items: SubItem[] }
  | { kind: "fetch"; load: () => Promise<SubItem[]> };

// sym's subpages — the SAME list drives the in-page tab strip (app/sym/layout.tsx) and the
// sidebar submenu. Tab active-state is an EXACT pathname match; keep hrefs canonical.
export const SYM_SUBNAV: SubItem[] = [
  { href: "/sym", label: "Universes" },
  { href: "/sym/overview", label: "Overview" },
  { href: "/sym/explorer", label: "Explorer" },
  { href: "/sym/heatmap", label: "Heat map" },
  { href: "/sym/attention", label: "Attention" },
  { href: "/sym/validation", label: "Validation" },
  { href: "/sym/operate", label: "Operate" },
];

// macro's submenu is data-driven: categories live in the macro DB (the category column is the
// source of truth), so the submenu can never drift. The caller owns the fail-safe (a failed or
// late fetch must never wipe a working submenu) — this just maps rows to SubItems.
async function loadMacroCategories(): Promise<SubItem[]> {
  const r = await fetch("/api/macro/categories", { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}`);
  const cats: CategorySummary[] = await r.json();
  return cats.map((c) => ({
    href: `/macro/${encodeURIComponent(c.category)}`,
    label: c.category,
    badge: c.n_series,
  }));
}

// The registry. Add a module's submenu here (static list or fetch loader) — that is the ONLY
// edit needed to give a new module a submenu; the shell render code is module-agnostic.
export const SUBNAV_PROVIDERS: Record<string, SubnavProvider> = {
  sym: { kind: "static", items: SYM_SUBNAV },
  macro: { kind: "fetch", load: loadMacroCategories },
};
