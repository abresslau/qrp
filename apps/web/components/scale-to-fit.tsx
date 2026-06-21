"use client";

import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

// Scales its content uniformly to fit the available box ("contain": fills as much as possible while
// keeping the content's natural proportions). A board then looks IDENTICAL on a laptop and a large
// screen — same layout, just larger — instead of sitting at laptop size and leaving dead space below.
// The fit is driven by whichever axis binds first (usually height for a wide screen).
//
// transform: scale keeps layout metrics stable (offsetWidth/offsetHeight are unaffected by transforms),
// so measuring the content can't feed back into the scale — no resize loop. Measurement happens in the
// ResizeObserver callback (async, post-layout), never synchronously in the effect body.
export function ScaleToFit({
  children,
  maxScale = 4,
  align = "top",
  className,
}: {
  children: ReactNode;
  maxScale?: number; // cap so a tiny board doesn't balloon absurdly on a huge screen
  align?: "top" | "center";
  className?: string;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const box = boxRef.current;
    const content = contentRef.current;
    if (!box || !content || typeof ResizeObserver === "undefined") return; // jsdom has no RO
    const ro = new ResizeObserver(() => {
      const aw = box.clientWidth;
      const ah = box.clientHeight;
      const cw = content.offsetWidth; // layout size — unaffected by the scale transform
      const ch = content.offsetHeight;
      if (cw && ch && aw && ah) setScale(Math.min(aw / cw, ah / ch, maxScale));
    });
    ro.observe(box);
    ro.observe(content);
    return () => ro.disconnect();
  }, [maxScale]);

  return (
    <div
      ref={boxRef}
      className={`flex h-full w-full justify-center overflow-hidden ${align === "center" ? "items-center" : "items-start"} ${className ?? ""}`}
    >
      <div ref={contentRef} className="shrink-0" style={{ transform: `scale(${scale})`, transformOrigin: align === "center" ? "center" : "top center" }}>
        {children}
      </div>
    </div>
  );
}
