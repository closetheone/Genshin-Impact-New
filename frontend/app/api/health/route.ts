import { backendHeaders, backendUrl } from "@/lib/backend";

export async function GET() {
  const request = new URLSearchParams({ snapshot: "fixture-2026-10-10-v1", scope: "opening", purpose: "display" });
  try {
    const response = await fetch(`${backendUrl}/api/status?${request}`, {
      headers: backendHeaders(),
      cache: "no-store",
    });
    if (!response.ok) {
      return Response.json({ ok: false, next: "ok", python: "error", python_status: response.status }, { status: 503 });
    }
    const payload = await response.json() as {
      snapshot_id?: string;
      source_admission?: { ready?: boolean };
      real_data_readiness?: { ready?: boolean; blockers?: string[] };
    };
    return Response.json({
      ok: true,
      next: "ok",
      python: "ok",
      snapshot_id: payload.snapshot_id || null,
      source_admission_ready: payload.source_admission?.ready ?? false,
      real_data_ready: payload.real_data_readiness?.ready ?? false,
      real_data_blockers: payload.real_data_readiness?.blockers || [],
    }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ ok: false, next: "ok", python: "unavailable" }, { status: 503 });
  }
}
