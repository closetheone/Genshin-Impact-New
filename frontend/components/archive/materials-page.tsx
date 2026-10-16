"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { archiveParams, DEFAULT_SNAPSHOT, type MaterialResult, type MaterialSelection } from "./types";

const STORAGE_KEY = "story-archive-materials-v1";
const emptySelection = (): MaterialSelection => ({ version: 1, snapshot: null, topic: "", passage_ids: [], relationships: [] });

function readSelection(): MaterialSelection {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return emptySelection();
  const value = JSON.parse(raw) as MaterialSelection;
  if (value.version !== 1 || (value.snapshot !== null && typeof value.snapshot !== "string") || typeof value.topic !== "string" || !Array.isArray(value.passage_ids) || !Array.isArray(value.relationships)) throw new Error("本地清单格式损坏或版本不支持。可以清空后新建清单。");
  return value;
}

function saveSelection(selection: MaterialSelection) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
}

export function MaterialsPage() {
  const [selection, setSelection] = useState<MaterialSelection>(() => typeof window === "undefined" ? emptySelection() : (() => { try { return readSelection(); } catch { return emptySelection(); } })());
  const [result, setResult] = useState<MaterialResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function loadSelection() {
    try { setSelection(readSelection()); setError(null); } catch (reason) { setError(reason instanceof Error ? reason.message : "本地清单暂不可用"); }
  }

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      setBusy(true);
      const snapshot = selection.snapshot || DEFAULT_SNAPSHOT;
      const request = { snapshot, scope_ids: ["opening", "east", "west", "later"], purpose: "display", topic: selection.topic, passage_ids: selection.passage_ids, relationships: selection.relationships };
      const response = await fetch("/api/materials", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request), cache: "no-store", signal: controller.signal });
      const data = await response.json() as MaterialResult & { error?: string };
      if (!response.ok) throw new Error(data.error || "素材核验失败");
      setResult(data);
      if (!selection.snapshot && data.snapshot_id && selection.passage_ids.length + selection.relationships.length) { const next = { ...selection, snapshot: data.snapshot_id }; saveSelection(next); setSelection(next); }
    };
    run().catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "素材核验失败"); }).finally(() => setBusy(false));
    return () => controller.abort();
  }, [selection]);

  function updateTopic(topic: string) {
    if (!selection) return;
    const next = { ...selection, topic: topic.slice(0, 500) };
    saveSelection(next); setSelection(next);
  }

  function clear() { window.localStorage.removeItem(STORAGE_KEY); setSelection(emptySelection()); setResult(null); setError(null); }

  function exportFile(kind: "md" | "json") {
    if (!result?.valid || !result.count) return;
    const body = kind === "md" ? result.markdown || "" : JSON.stringify(result.package, null, 2);
    const blob = new Blob([body], { type: kind === "md" ? "text/markdown;charset=utf-8" : "application/json" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `synthetic-materials.${kind}`; anchor.click(); URL.revokeObjectURL(url);
  }

  const selected = selection || emptySelection();
  return <main className="mx-auto min-h-screen max-w-6xl px-5 py-10 sm:px-8"><header className="mb-8"><Link href="/" className="text-xs font-semibold uppercase tracking-[0.3em] text-gold">Genshin Impact · archive</Link><h1 className="mt-3 font-serif text-4xl tracking-tight text-ink sm:text-5xl">素材清单</h1><p className="mt-3 max-w-2xl leading-7 text-muted">清单只保存在当前浏览器。服务端会按当前快照、范围和用途重新核验，核验失败的内容不会进入预览或导出。</p></header><section className="rounded-2xl border border-line bg-panel p-5 shadow-sm"><label className="text-sm font-medium">创作主题 / 备注<textarea value={selected.topic} onChange={(event) => updateTopic(event.target.value)} maxLength={500} rows={3} placeholder="例如：围绕师徒关系整理可追溯证据" className="mt-1.5 w-full rounded-lg border border-line bg-paper p-3 outline-none focus:border-green focus:ring-2 focus:ring-green/20" /></label><div className="mt-4 flex flex-wrap gap-3 text-sm text-muted"><span>固定快照：<code>{selected.snapshot || "加入第一项后固定"}</code></span><span>原文 {selected.passage_ids.length} 项</span><span>关系 {selected.relationships.length} 项</span></div>{error ? <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">{error}</div> : null}{busy ? <p className="mt-5 text-muted">正在重新核验素材…</p> : null}{result && !result.valid ? <div className="mt-5 rounded-xl border border-gold/40 bg-gold/10 p-4 text-ink">部分素材在当前范围或用途下不可用，请移除失效项后再导出。</div> : null}<div className="mt-6">{result && selected.passage_ids.length + selected.relationships.length ? <ul className="space-y-3">{[...result.preview.passages.map((item) => ({ kind: "原文", id: item.id, text: item.text })), ...result.preview.relationships.map((item) => ({ kind: "关系与完整证据", id: item.id, text: item.description }))].map((item) => <li key={`${item.kind}-${item.id}`} className="flex items-start justify-between gap-4 rounded-xl border border-line bg-paper p-4"><div><span className="rounded-full bg-green/10 px-2 py-1 text-xs text-green">{item.kind}</span><code className="ml-2 text-xs">{item.id}</code><p className="mt-2 leading-6">{item.text}</p>{item.kind === "原文" ? <Link className="mt-2 inline-block text-sm text-green hover:underline" href={`/read?passage=${encodeURIComponent(item.id)}&snapshot=${encodeURIComponent(selected.snapshot || DEFAULT_SNAPSHOT)}&scope=all&purpose=display`}>回到原文 ↗</Link> : null}</div></li>)}</ul> : <div className="rounded-xl border border-dashed border-line p-8 text-center text-muted"><p>还没有素材。</p><p className="mt-2 text-sm">从搜索结果、原文阅读或关系证据页面加入后，会在这里按完整证据核验。</p></div>}</div><div className="mt-6 flex flex-wrap gap-3"><Button variant="outline" onClick={loadSelection}>重新读取</Button><Button variant="outline" onClick={clear}>清空并新建清单</Button><Button disabled={!result?.valid || !result.count} onClick={() => exportFile("md")}>导出 Markdown</Button><Button variant="outline" disabled={!result?.valid || !result.count} onClick={() => exportFile("json")}>导出 JSON</Button></div></section></main>;
}
