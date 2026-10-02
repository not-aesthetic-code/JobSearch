import { proxy } from "@/lib/api";

const ACTIONS = new Set(["seen", "applied", "dismissed", "apply"]);

export async function POST(_: Request, { params }: { params: Promise<{ id: string; action: string }> }) {
  const { id, action } = await params;
  if (!ACTIONS.has(action)) return new Response(null, { status: 404 });
  const response = await proxy(`/shortlist/${encodeURIComponent(id)}/${action}`, { method: "POST" });
  // 204 must not carry a body
  return response.status === 204 ? new Response(null, { status: 204 }) : response;
}
