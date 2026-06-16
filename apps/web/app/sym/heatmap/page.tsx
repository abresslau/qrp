import { HeatmapView } from "@/components/heatmap-view";
import { apiGet } from "@/lib/api";

type UniverseRef = { universe_id: string; name: string; members_resolved: number };
type WindowOpt = { code: string; label: string };

export default async function HeatmapPage({
  searchParams,
}: {
  searchParams: Promise<{ u?: string }>;
}) {
  const { u } = await searchParams;
  let universes: UniverseRef[] = [];
  let windows: WindowOpt[] = [];
  try {
    universes = await apiGet<UniverseRef[]>("/api/sym/universes");
  } catch {
    universes = [];
  }
  try {
    windows = await apiGet<WindowOpt[]>("/api/sym/return-windows");
  } catch {
    windows = [];
  }
  const fallback = universes.some((x) => x.universe_id === "sp500")
    ? "sp500"
    : (universes[0]?.universe_id ?? "sp500");
  const defaultUniverse = u && universes.some((x) => x.universe_id === u) ? u : fallback;

  return (
    <HeatmapView
      universes={universes}
      windows={windows}
      defaultUniverse={defaultUniverse}
      defaultWindow="1D"
    />
  );
}
