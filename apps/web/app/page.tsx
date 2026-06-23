import { DataSnapshotCards } from "@/components/data-snapshot-cards";

// Platform home — an at-a-glance market dashboard (rates / indices / FX snapshot cards), each
// linking to its full view. Renders inside the app shell; the sidebar brand links here.
export default function Home() {
  return (
    <div className="w-full">
      <header className="mb-5">
        <h1 className="text-xl font-semibold tracking-tight text-fg 2xl:text-2xl">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">A market snapshot across the platform — tap a card for the full view.</p>
      </header>
      <DataSnapshotCards />
    </div>
  );
}
