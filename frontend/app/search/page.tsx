import { Suspense } from "react";
import { SearchPage } from "@/components/archive/search-page";

function SearchFallback() {
  return <main className="mx-auto min-h-screen max-w-7xl px-5 py-10"><p className="text-muted">正在打开文本检索…</p></main>;
}

export default function SearchRoute() {
  return <Suspense fallback={<SearchFallback />}><SearchPage /></Suspense>;
}
