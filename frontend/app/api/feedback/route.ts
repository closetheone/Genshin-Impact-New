const BACKEND = "http://127.0.0.1:4175";

export async function POST(request: Request) {
  try {
    const response = await fetch(`${BACKEND}/api/feedback`, { method: "POST", headers: new Headers({ Host: "127.0.0.1:4175", Origin: BACKEND, "Content-Type": request.headers.get("content-type") || "application/json" }), body: await request.text(), cache: "no-store" });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { "Content-Type": response.headers.get("content-type") || "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Python API 暂不可用，请先启动本地服务。" }, { status: 503 });
  }
}
