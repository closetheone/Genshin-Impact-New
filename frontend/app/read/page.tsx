import { Suspense } from "react";
import { ReaderPage } from "@/components/archive/reader-page";

function ReaderFallback() {
  return <main className="mx-auto min-h-screen max-w-7xl px-5 py-10"><p className="text-muted">正在打开原文阅读…</p></main>;
}

export default function ReadRoute() {
  return <Suspense fallback={<ReaderFallback />}><ReaderPage /></Suspense>;
}
