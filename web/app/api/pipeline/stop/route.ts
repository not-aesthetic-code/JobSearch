import { proxy } from "@/lib/api";

export async function POST() {
  return proxy("/pipeline/stop", { method: "POST" });
}
