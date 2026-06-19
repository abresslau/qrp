import { MacroBrowser } from "@/components/macro-browser";
import { MacroPopulationMap } from "@/components/macro-population-map";

// Static segment — takes precedence over the dynamic /macro/[category] route for this exact
// path. The "population" category gets a world map on top of the normal series browser; every
// other category still falls through to /macro/[category].
export default function MacroPopulationPage() {
  return (
    <div>
      <MacroPopulationMap />
      <div className="mt-8">
        <MacroBrowser category="population" />
      </div>
    </div>
  );
}
