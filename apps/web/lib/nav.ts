// Per-module sidebar sub-navigation (Story C.1).
//
// Two providers, deliberately NOT a framework (extract one when module #3 wants a submenu):
// - STATIC_SUBNAV: hand-declared page lists (sym — single source shared with its tab strip).
// - macro: data-driven from GET /api/macro/categories, fetched inside the Sidebar so the
//   submenu can never drift from the data (the category column is the source of truth).

export type SubItem = { href: string; label: string; badge?: number };

// sym's subpages — the SAME list drives the in-page tab strip (app/sym/layout.tsx) and the
// sidebar submenu. Tab active-state is an EXACT pathname match; keep hrefs canonical.
export const SYM_SUBNAV: SubItem[] = [
  { href: "/sym", label: "Overview" },
  { href: "/sym/explorer", label: "Explorer" },
  { href: "/sym/universes", label: "Universes" },
  { href: "/sym/heatmap", label: "Heat map" },
  { href: "/sym/attention", label: "Attention" },
  { href: "/sym/validation", label: "Validation" },
  { href: "/sym/operate", label: "Operate" },
];

export const STATIC_SUBNAV: Record<string, SubItem[]> = {
  sym: SYM_SUBNAV,
};
