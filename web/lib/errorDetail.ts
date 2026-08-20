// FastAPI's error body is {detail: string | ...}. Takes the already-parsed
// body (not the Response) since callers on the success path also need to
// read that body, and a Response can only be read once.
export function errorDetail(body: unknown, fallback = "Request failed"): string {
  return typeof (body as { detail?: unknown } | null)?.detail === "string"
    ? (body as { detail: string }).detail
    : fallback;
}
