import { Suspense } from "react";
import { AboutPage } from "@/components/archive/about-page";

export default function AboutRoute() {
  return <Suspense fallback={<main className="mx-auto min-h-screen max-w-6xl px-5 py-10"><p className="text-muted">正在读取收录状态…</p></main>}><AboutPage /></Suspense>;
}
