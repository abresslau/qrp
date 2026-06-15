"use client";

// Command palette (FR-2). Opens from anywhere with ⌘K (macOS) / Ctrl+K (else); Esc or a
// backdrop click closes. Lists every enabled module AREA and its SCREENS — sourced from the
// SAME registry the sidebar uses (lib/nav.ts SUBNAV_PROVIDERS), so the two never drift — plus
// the FR-7 OPERATIONS. Substring filter; ↑/↓ move the selection; Enter acts. Read-only ops
// launch directly (POST /api/operate/run) then route to Operate to watch the job; writer /
// arg-taking ops route to /sym/operate where the confirm + universe/scope guard UX lives.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { Schemas } from "@/lib/api";
import { SUBNAV_PROVIDERS } from "@/lib/nav";

type Module = { key: string; name: string; description: string; enabled: boolean };
type OpDef = Schemas["OpDef"];

type Entry =
  | { kind: "area"; group: "Areas"; label: string; href: string }
  | { kind: "screen"; group: "Screens"; label: string; href: string }
  | { kind: "op"; group: "Operations"; label: string; op: OpDef };

export function CommandPalette({ modules }: { modules: Module[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const [ops, setOps] = useState<OpDef[]>([]);
  const [asyncScreens, setAsyncScreens] = useState<Record<string, ReadonlyArray<{ href: string; label: string }>>>({});
  const [msg, setMsg] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const loadedRef = useRef(false);

  // Global open/close shortcut. ⌘K/Ctrl+K toggles from anywhere (captured even inside inputs —
  // the modifier makes it unambiguous); Esc closes. Setting state in an event handler (not in
  // an effect body) keeps clear of react-hooks/set-state-in-effect.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setQuery("");
        setSel(0);
        setMsg("");
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Lazy-load on first open (cached for the session): the FR-7 ops, and any async submenu
  // providers (e.g. macro). All sets happen in promise callbacks, never synchronously here.
  useEffect(() => {
    if (!open || loadedRef.current) return;
    fetch("/api/operate/ops", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((d: OpDef[]) => {
        setOps(Array.isArray(d) ? d : []);
        loadedRef.current = true; // latch only on success → a failed load retries on reopen
      })
      .catch(() => {});
    for (const m of modules.filter((x) => x.enabled)) {
      const p = SUBNAV_PROVIDERS[m.key];
      if (p?.kind === "fetch") {
        p.load()
          .then((sub) => setAsyncScreens((s) => ({ ...s, [m.key]: sub })))
          .catch(() => {});
      }
    }
  }, [open, modules]);

  // Focus the search field when the palette opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const entries = useMemo<Entry[]>(() => {
    const enabled = modules.filter((m) => m.enabled);
    const areas: Entry[] = enabled.map((m) => ({
      kind: "area",
      group: "Areas",
      label: m.name,
      href: `/${m.key}`,
    }));
    const screens: Entry[] = [];
    for (const m of enabled) {
      const p = SUBNAV_PROVIDERS[m.key];
      const items = !p ? [] : p.kind === "static" ? p.items : (asyncScreens[m.key] ?? []);
      for (const it of items) {
        screens.push({ kind: "screen", group: "Screens", label: `${m.name}: ${it.label}`, href: it.href });
      }
    }
    const opEntries: Entry[] = ops.map((op) => ({
      kind: "op",
      group: "Operations",
      label: `Run: ${op.label}`,
      op,
    }));
    return [...areas, ...screens, ...opEntries];
  }, [modules, asyncScreens, ops]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? entries.filter((e) => e.label.toLowerCase().includes(q)) : entries;
  }, [entries, query]);

  const selSafe = filtered.length ? Math.min(sel, filtered.length - 1) : 0;

  const act = useCallback(
    (entry?: Entry) => {
      if (!entry) return;
      if (entry.kind === "area" || entry.kind === "screen") {
        setOpen(false);
        router.push(entry.href);
        return;
      }
      // Operation. A writer/arg-taking op routes to Operate, where the confirm + universe/scope
      // guard UX already lives (not duplicated here). A read-only op (no writes, no universe/
      // scope) launches directly and we surface the result: on success route to /sym/operate so
      // the job (and its id) shows live via the SSE stream; on rejection (e.g. a duplicate-run
      // conflict — no job row is created) show the reason inline and keep the palette open.
      const op = entry.op;
      const readOnly = !op.writes && !op.takes_universe && !op.takes_scope;
      if (!readOnly) {
        setOpen(false);
        router.push("/sym/operate");
        return;
      }
      setMsg(`Starting ${op.label}…`);
      fetch("/api/operate/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: op.key, args: [], confirm: false }),
      })
        .then(async (r) => {
          // O.4 envelope: {error:{message}} on failure, RunResult {ok,job_id,reason} on success.
          const res: { ok?: boolean; job_id?: number; reason?: string; error?: { message?: string } } =
            await r.json().catch(() => ({}));
          if (r.ok && res.ok) {
            setOpen(false);
            router.push("/sym/operate");
          } else {
            setMsg(`Rejected: ${res.error?.message ?? res.reason ?? "unknown"}`);
          }
        })
        .catch(() => setMsg("Run failed — open Operate to retry"));
    },
    [router],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh]"
      onClick={() => setOpen(false)}
      role="presentation"
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
            setMsg("");
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setSel((s) => Math.min(filtered.length - 1, s + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setSel((s) => Math.max(0, s - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              act(filtered[selSafe]);
            }
          }}
          placeholder="Jump to a module, screen, or operation…"
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm text-fg placeholder:text-muted focus:outline-none"
        />
        <ul className="max-h-80 overflow-auto py-1">
          {filtered.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-muted">No matches.</li>
          )}
          {filtered.map((e, i) => {
            const active = i === selSafe;
            const prevGroup = i > 0 ? filtered[i - 1].group : null;
            return (
              <li key={`${e.kind}-${e.label}-${i}`}>
                {e.group !== prevGroup && (
                  <div className="px-4 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wide text-muted">
                    {e.group}
                  </div>
                )}
                <button
                  type="button"
                  onMouseEnter={() => setSel(i)}
                  onClick={() => act(e)}
                  className={[
                    "flex w-full items-center px-4 py-2 text-left text-sm transition",
                    active ? "bg-fg/10 text-fg" : "text-muted hover:bg-fg/5 hover:text-fg",
                  ].join(" ")}
                >
                  {e.label}
                </button>
              </li>
            );
          })}
        </ul>
        <div className="border-t border-border px-4 py-2 text-[11px] text-muted">
          {msg || "↑↓ navigate · ↵ select · esc close"}
        </div>
      </div>
    </div>
  );
}
