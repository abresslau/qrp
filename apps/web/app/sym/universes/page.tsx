import { redirect } from "next/navigation";

// Universes is now the sym landing page (/sym). This old route redirects there so
// bookmarks and the heatmap "← Universes" links keep working.
export default function UniversesRedirect() {
  redirect("/sym");
}
