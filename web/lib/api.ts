// Server-side proxy to the FastAPI backend — the API key never reaches the browser.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    ...(init?.headers as Record<string, string> | undefined), // callers override it for PDF uploads
  };
  if (process.env.API_KEY) headers.authorization = `Bearer ${process.env.API_KEY}`;
  return fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
}

export async function proxy(path: string, init?: RequestInit): Promise<Response> {
  const response = await apiFetch(path, init);
  return new Response(response.body, {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
