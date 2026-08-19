import { proxy } from "@/lib/api";

export async function GET(request: Request) {
  // forward ?limit&offset untouched — the backend validates them
  return proxy(`/shortlist${new URL(request.url).search}`);
}
