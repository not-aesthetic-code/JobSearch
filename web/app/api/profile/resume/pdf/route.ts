import { proxy } from "@/lib/api";

export async function PUT(request: Request) {
  // arrayBuffer, not the stream: a streamed body would need `duplex: "half"`
  return proxy("/profile/resume/pdf", {
    method: "PUT",
    body: await request.arrayBuffer(),
    headers: { "content-type": "application/pdf" },
  });
}
