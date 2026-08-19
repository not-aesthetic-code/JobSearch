import { proxy } from "@/lib/api";

export async function GET() {
  return proxy("/profile/resume");
}

export async function PUT(request: Request) {
  return proxy("/profile/resume", { method: "PUT", body: await request.text() });
}
