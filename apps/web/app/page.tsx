import { redirect } from "next/navigation";

// The platform landing routes to the first enabled module area (sym → its Overview).
export default function Home() {
  redirect("/sym");
}
