// Shared ticker-convention preference — one global choice (Bloomberg Region / Exchange / FactSet /
// Plain) honored by every surface that shows a ticker (Explorer, security detail, portfolio pivot).
// Persisted to localStorage, read via useSyncExternalStore (the project's prefs contract: stable
// server snapshot = the default so SSR/hydration match, then the client snapshot takes over).
// Default = Bloomberg Region ("ADS GR"). A stale/garbage stored value falls back to the default.

import { useSyncExternalStore } from "react";

import { TICKER_CONVENTIONS, type TickerConvention } from "@/lib/ticker";

const KEY = "qrp.ticker.convention";
const DEFAULT: TickerConvention = "bbg-region";
const listeners = new Set<() => void>();

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("storage", cb); // cross-tab
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}
function read(): TickerConvention {
  try {
    const v = localStorage.getItem(KEY);
    return TICKER_CONVENTIONS.some((c) => c.value === v) ? (v as TickerConvention) : DEFAULT;
  } catch {
    return DEFAULT;
  }
}
function readServer(): TickerConvention {
  return DEFAULT; // SSR + hydration render with the default; the client store takes over after
}

export function setTickerConvention(v: TickerConvention): void {
  try {
    localStorage.setItem(KEY, v);
    listeners.forEach((l) => l()); // notify this tab (the storage event is cross-tab only)
  } catch {
    /* storage unavailable — the choice just won't persist */
  }
}

export function useTickerConvention(): TickerConvention {
  return useSyncExternalStore(subscribe, read, readServer);
}
