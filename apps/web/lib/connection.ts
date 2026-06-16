import { useSyncExternalStore } from "react";

// Client-side "online/offline" toggle (the sidebar API icon). When offline, background polling —
// the API health check and the live-heatmap auto-refresh — is paused; flip back to resume. This is
// purely a frontend connect/pause; it does not stop the server process. A module-level store via
// useSyncExternalStore, shared across the indicator and the pollers. Session/tab-local by design
// (NOT persisted or cross-tab — unlike the theme store; a reload returns to online).
let online = true;
const listeners = new Set<() => void>();

export function setOnline(v: boolean): void {
  if (online === v) return;
  online = v;
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
function getSnapshot(): boolean {
  return online;
}
function getServerSnapshot(): boolean {
  return true; // SSR renders as online; the client store takes over after hydration
}

export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
