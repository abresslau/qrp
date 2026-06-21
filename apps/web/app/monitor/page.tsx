import { redirect } from "next/navigation";

// The Monitor area opens on the World equity indices board (its first screen).
export default function MonitorHome() {
  redirect("/monitor/wei");
}
