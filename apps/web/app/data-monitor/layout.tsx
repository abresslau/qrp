// Data Monitor — a single tab-less observability screen (the lone EOD tab was removed). This wrapper
// just sizes the area to the viewport (so the board fits without page scroll) and owns vertical
// overflow; the board itself lives at the area index (`page.tsx`).
export default function DataMonitorLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="-mt-3.5 flex h-[calc(100dvh-2rem)] w-full flex-col [@media(min-height:960px)]:-mt-2">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
    </div>
  );
}
