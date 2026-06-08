"use client";

import { useEffect, useState } from "react";

type Mode = "light" | "dark" | "system";

function prefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolvedDark(m: Mode): boolean {
  return m === "dark" || (m === "system" && prefersDark());
}

export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("dark");

  // Read the persisted choice on mount (the no-flash script already applied the class).
  useEffect(() => {
    setMode(((localStorage.getItem("qrp-theme") as Mode) || "dark") as Mode);
  }, []);

  // When in "system", follow OS changes live.
  useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => document.documentElement.classList.toggle("dark", mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  function change(m: Mode) {
    setMode(m);
    try {
      localStorage.setItem("qrp-theme", m);
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
