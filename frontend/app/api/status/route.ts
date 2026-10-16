const BACKEND = "http://127.0.0.1:4175";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const response = await fetch(`${BACKEND}/api/status${url.search}`, { headers: new Headers({ Host: "127.0.0.1:4175", Origin: BACKEND }), cache: "no-store" });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Python API 暂不可用，请先启动本地服务。" }, { status: 503 });
  }
}
