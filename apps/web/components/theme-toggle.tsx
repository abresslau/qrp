"use client";

import { useEffect, useSyncExternalStore } from "react";

type Mode = "light" | "dark" | "system";

const KEY = "qrp-theme";
const listeners = new Set<() => void>();

// Theme is an EXTERNAL store (localStorage). Reading it via useSyncExternalStore — instead of a
// useState + mount effect — removes the set-state-in-effect smell AND gives React a server
// snapshot ("dark", matching the no-flash script) so there's no hydration mismatch.
function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  window.addEventListener("storage", cb); // cross-tab changes
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}
function getSnapshot(): Mode {
  // Called during render by useSyncExternalStore — a throwing localStorage (private mode,
  // sandboxed iframe) must degrade to the default, never crash the render.
  try {
    return ((localStorage.getItem(KEY) as Mode) || "dark") as Mode;
  } catch {
    return "dark";
  }
}
function getServerSnapshot(): Mode {
  return "dark";
}

function prefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolvedDark(m: Mode): boolean {
  return m === "dark" || (m === "system" && prefersDark());
}

export function ThemeToggle() {
  const mode = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  // When in "system", follow OS changes live.
  useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => document.documentElement.classList.toggle("dark", mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  function change(m: Mode) {
    try {
      localStorage.setItem(KEY, m);
      listeners.forEach((l) => l()); // notify this tab (storage event only fires cross-tab)
    } catch {
      /* ignore */
    }
    document.documentElement.classList.toggle("dark", resolvedDark(m));
  }

  return (
    <label className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm text-muted">
      <span>Theme</span>
      <select
        value={mode}
        onChange={(e) => change(e.target.value as Mode)}
        className="bg-transparent font-medium text-fg outline-none"
      >
        <option value="light">Light</option>
        <option value="dark">Dark</option>
        <option value="system">System</option>
      </select>
    </label>
  );
}
