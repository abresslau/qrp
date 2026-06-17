"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

/**
 * Guards async *resolutions* against a context that changed while the request was in flight — the
 * recurring console-hardening pattern (a newer request supersedes an older one; a modal closes /
 * close→reopens; the component unmounts). One generation counter + mount-awareness, behind three
 * verbs so both trigger shapes are covered:
 *
 *   const guard = useRunGuard();
 *
 *   // (a) Event-handler-triggered concurrent ops — e.g. a mount load + a retry + a post-create
 *   //     reload that can overlap. `begin()` starts a new run (bumps the generation) and returns
 *   //     its validity check:
 *   const isCurrent = guard.begin();
 *   fetchData().then((d) => { if (isCurrent()) setRows(d); }).catch(() => { if (isCurrent()) setError(); });
 *
 *   // (b) An external event opening a NEW session — e.g. a command palette reopening. `supersede()`
 *   //     invalidates prior in-flight runs without capturing; `capture()` binds to the current
 *   //     generation at op-launch:
 *   useEffect(() => { if (open) guard.supersede(); }, [open, guard]);
 *   const isCurrent = guard.capture();
 *   runOp().then(() => { if (isCurrent()) navigate(); });
 *
 * `isCurrent()` returns false once a newer run/session has started OR the component unmounted.
 *
 * NOT an AbortController: this guards the resolution, it does NOT cancel the network request. Use a
 * real AbortController where you want to actually abort a cancellable/supersedable fetch.
 */
export function useRunGuard() {
  const genRef = useRef(0);
  const mountedRef = useRef(true);
  useEffect(() => {
    // Set on (re)mount too, not just via the initial value — StrictMode mounts, unmounts (→false),
    // then remounts, and a plain useRef(true) would stay false after that cycle.
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const begin = useCallback(() => {
    const gen = ++genRef.current;
    return () => mountedRef.current && genRef.current === gen;
  }, []);

  const capture = useCallback(() => {
    const gen = genRef.current;
    return () => mountedRef.current && genRef.current === gen;
  }, []);

  const supersede = useCallback(() => {
    genRef.current += 1;
  }, []);

  // Stable object so callers can list `guard` in an effect dep array without churn.
  return useMemo(() => ({ begin, capture, supersede }), [begin, capture, supersede]);
}
