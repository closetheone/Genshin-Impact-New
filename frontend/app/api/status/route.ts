import { backendHeaders, backendUrl } from "@/lib/backend";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const response = await fetch(`${backendUrl}/api/status${url.search}`, { headers: backendHeaders(), cache: "no-store" });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Python API 暂不可用，请先启动本地服务。" }, { status: 503 });
  }
}
