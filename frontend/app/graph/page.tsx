import { Suspense } from "react";
import { GraphPage } from "@/components/archive/graph-page";

function GraphFallback() {
  return <main className="mx-auto min-h-screen max-w-7xl px-5 py-10"><p className="text-muted">正在打开人物关系图…</p></main>;
}

export default function GraphRoute() {
  return <Suspense fallback={<GraphFallback />}><GraphPage /></Suspense>;
}
