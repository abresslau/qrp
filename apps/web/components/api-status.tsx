"use client";

import { useEffect, useState } from "react";

import { setOnline, useOnline } from "@/lib/connection";

type Health = "checking" | "up" | "down";

// API status indicator + offline toggle for the sidebar (icon only — colour carries state, words
// live in the tooltip). When ONLINE it polls health every 15s: green = reachable, red = unreachable,
// amber pulse = checking. Clicking toggles OFFLINE (grey, hollow): background polling here and the
// live-heatmap auto-refresh pause; click again to reconnect. Frontend connect/pause only — it does
// not stop the server.
export function ApiStatus() {
  const online = useOnline();
  const [health, setHealth] = useState<Health>("checking");
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  useEffect(() => {
    if (!online) return; // offline: stop polling entirely
    const ac = new AbortController();
    const ping = async () => {
      try {
        const r = await fetch("/api/sym/health", { cache: "no-store", signal: ac.signal });
        if (!ac.signal.aborted) setHealth(r.ok ? "up" : "down");
      } catch {
        if (!ac.signal.aborted) setHealth("down"); // ignores the AbortError on teardown
      } finally {
        if (!ac.signal.aborted) {
          setCheckedAt(new Date().toLocaleTimeString(undefined, { timeZoneName: "short" }));
        }
      }
    };
    void ping();
    const id = setInterval(() => void ping(), 15000);
    return () => {
      ac.abort(); // cancel any in-flight health fetch + guard its setState
      clearInterval(id);
    };
  }, [online]);

  // Display state: offline (user-paused) is distinct from down (tried + unreachable).
  const state = !online ? "off" : health;
  const color =
    state === "up"
      ? "text-emerald-500"
      : state === "down"
        ? "text-rose-500"
        : state === "checking"
          ? "text-amber-500"
          : "text-muted"; // off
  const title =
    state === "off"
      ? "Offline — API polling paused · click to reconnect"
      : state === "up"
        ? `API connected${checkedAt ? ` · checked ${checkedAt}` : ""} · click to go offline`
        : state === "down"
          ? `API unreachable${checkedAt ? ` · checked ${checkedAt}` : ""} · click to go offline`
          : "Checking API… · click to go offline";

  return (
    <button
      type="button"
      onClick={() => setOnline(!online)}
      title={title}
      aria-label={title}
      className={`inline-flex h-4 w-4 items-center justify-center ${color}`}
      data-status={state}
    >
      <svg
        viewBox="0 0 8 8"
        aria-hidden="true"
        className={`h-2.5 w-2.5 ${state === "checking" ? "animate-pulse" : ""}`}
      >
        {/* filled when monitoring; hollow ring when offline */}
        <circle
          cx="4"
          cy="4"
          r={state === "off" ? 3 : 4}
          fill={state === "off" ? "none" : "currentColor"}
          stroke="currentColor"
          strokeWidth={state === "off" ? 1.5 : 0}
        />
      </svg>
    </button>
  );
}
