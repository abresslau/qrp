// Server-side API client. Server Components fetch the API directly (absolute base);
// browser calls use the Next rewrites proxy (/api/*). Always live — numbers tie to sym.
//
// Types are GENERATED from the FastAPI OpenAPI schema (`npm run gen:types` ->
// lib/api-types.ts). `Schemas` re-exports the component models so pages annotate
// fetches with the same shapes the API actually returns. `apiGetTyped` keys
// parameterless GET paths to their 200 response type for compile-time safety.
import type { components, paths } from "./api-types";

const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8001";

/** Component response/request models straight from the OpenAPI schema. */
export type Schemas = components["schemas"];

/** Untyped escape hatch — caller supplies the expected shape (e.g. generated Schemas[...]). */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return (await res.json()) as T;
}

// --- typed GET keyed to the OpenAPI `paths` (for routes without path params) ---
type JsonContent<R> = R extends { content: { "application/json": infer J } } ? J : never;
type Ok200<P extends keyof paths> = paths[P] extends {
  get: { responses: { 200: infer R } };
}
  ? JsonContent<R>
  : never;

/** GET a known schema path; the return type is inferred from the OpenAPI 200 response. */
export async function apiGetTyped<P extends keyof paths>(path: P): Promise<Ok200<P>> {
  return apiGet<Ok200<P>>(path as string);
}
