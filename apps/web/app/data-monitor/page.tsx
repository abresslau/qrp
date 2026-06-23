import { redirect } from "next/navigation";

// The Data Monitor area opens on the EOD freshness board (its first screen).
export default function DataMonitorHome() {
  redirect("/data-monitor/eod");
}
