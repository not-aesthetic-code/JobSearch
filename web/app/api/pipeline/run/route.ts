import { proxy } from "@/lib/api";

export async function POST(request: Request) {
  return proxy("/pipeline/run", { method: "POST", body: await request.text() });
}
