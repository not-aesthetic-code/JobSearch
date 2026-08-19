import { proxy } from "@/lib/api";

export async function GET() {
  return proxy("/pipeline/status");
}
