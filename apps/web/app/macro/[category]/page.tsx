"use client";

import { use } from "react";

import { MacroBrowser } from "@/components/macro-browser";

// `params` is a Promise in this Next.js version — client pages unwrap it with React's
// `use()` (node_modules/next/dist/docs/01-app/.../dynamic-routes.md). The route matcher
// has ALREADY percent-decoded the segment (route-matcher.js) — decoding again would
// throw URIError on %-junk URLs and corrupt validly-encoded values. An unknown category
// is NOT a 404: the browser shows an honest empty state for it.
export default function MacroCategoryPage({
  params,
}: {
  params: Promise<{ category: string }>;
}) {
  const { category } = use(params);
  return <MacroBrowser category={category} />;
}
