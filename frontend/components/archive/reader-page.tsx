"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { archiveParams, DEFAULT_SNAPSHOT, normalizeScope, scopeLabel, speakerName, type ReaderView } from "./types";
import { addPassageToLocalSelection } from "./materials-client";

export function ReaderPage() {
  const searchParams = useSearchParams();
  const [view, setView] = useState<ReaderView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [cursor, setCursor] = useState(() => searchParams.get("cursor") || "");
  const snapshot = searchParams.get("snapshot") || DEFAULT_SNAPSHOT;
  const scope = normalizeScope(searchParams.get("scope"));
  const purpose = "display" as const;
  const target = searchParams.get("passage") || "";
  const from = searchParams.get("from");

  useEffect(() => {
    const controller = new AbortController();
    const request = archiveParams({ snapshot, scope, purpose });
    if (target) request.set("id", target);
    if (cursor) request.set("cursor", cursor);
    fetch(`/api/read?${request}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "原文读取失败"); if (data.dataset_kind !== "synthetic") throw new Error("此页面只接受明确标注的原创合成样本"); return data as ReaderView; })
      .then(setView)
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "原文读取失败"); });
    const params = new URLSearchParams({ passage: target, snapshot, scope, purpose });
    if (cursor) params.set("cursor", cursor);
    window.history.replaceState(null, "", `/read?${params}`);
    return () => controller.abort();
  }, [cursor, scope, snapshot, target]);

  const labels = useMemo(() => new Map((view?.characters || []).map((character) => [character.id, character.name])), [view]);
  const title = view?.entries[0]?.title || "原文阅读";
  const searchHref = from ? `/search?${from}` : `/search?snapshot=${encodeURIComponent(snapshot)}&scope=${encodeURIComponent(scope)}&purpose=display`;

  if (error) return <main className="mx-auto min-h-screen max-w-5xl px-5 py-10"><div className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">{error}</div><Link className="mt-5 inline-block text-green hover:underline" href={searchHref}>← 返回文本检索</Link></main>;
  return <main className="mx-auto min-h-screen max-w-7xl px-5 py-10 sm:px-8"><div className="mb-8 flex flex-wrap items-center justify-between gap-3"><Link className="text-sm font-medium text-green hover:underline" href={searchHref}>← 返回文本检索</Link><span className="text-xs text-muted">快照：{snapshot}</span></div>{notice ? <p className="mb-4 rounded-lg bg-green/10 p-3 text-sm text-green" role="status">{notice}</p> : null}{!view ? <p className="text-muted">正在读取原文上下文…</p> : <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_280px]"><article className="rounded-3xl border border-line bg-panel p-5 shadow-sm sm:p-8"><header className="border-b border-line pb-6"><p className="text-xs font-semibold uppercase tracking-[0.25em] text-gold">Original synthetic fixture</p><h1 className="mt-3 font-serif text-4xl tracking-tight">{title}</h1><div className="mt-3 flex flex-wrap gap-2 text-sm text-muted"><span>{view.pagination.total} 段可见文本</span><span>·</span><span>按显式对话连接排序</span></div></header><div className="my-6 flex items-center justify-between gap-3"><Button variant="outline" disabled={!view.pagination.previous_cursor} onClick={() => setCursor(view.pagination.previous_cursor || "")}>上一页</Button><span className="text-sm text-muted">第 {Math.floor(view.pagination.offset / view.pagination.limit) + 1} 页</span><Button variant="outline" disabled={!view.pagination.next_cursor} onClick={() => setCursor(view.pagination.next_cursor || "")}>下一页</Button></div><div className="space-y-4">{view.passages.map((passage) => <section key={passage.id} id={passage.id} className={`scroll-mt-6 rounded-2xl border p-5 ${passage.id === view.target_id ? "border-gold bg-gold/5" : "border-line bg-paper"}`}><div className="flex flex-wrap items-center gap-2 text-xs text-muted"><span className="rounded-full bg-green/10 px-2 py-1 text-green">{scopeLabel(passage)}</span><span>{speakerName(view.characters, passage.speaker_id)}</span><code>{passage.id}</code></div><p className="mt-3 text-lg leading-9">{passage.text}</p><div className="mt-3 flex flex-wrap gap-3 text-xs"><button type="button" className="text-green hover:underline" onClick={() => { try { addPassageToLocalSelection(passage.id, view.snapshot_id); setNotice(`已加入 ${passage.id}，请到素材清单重新核验。`); } catch (reason) { setNotice(reason instanceof Error ? reason.message : "加入素材失败"); } }}>加入素材 ＋</button></div><details className="mt-4 text-sm text-muted"><summary className="cursor-pointer">出处与对话连接</summary><div className="mt-3 space-y-2"><p><code>{passage.source_id}</code><br />{passage.source_locator}</p><p>当前可见后续：{passage.next_ids.length ? passage.next_ids.map((id) => <Link key={id} className="ml-2 text-green hover:underline" href={`/read?passage=${encodeURIComponent(id)}&snapshot=${encodeURIComponent(snapshot)}&scope=${encodeURIComponent(scope)}&purpose=display`}>{id}</Link>) : "无（不表示完整剧情结束）"}</p></div></details></section>)}</div></article><aside className="space-y-4"><div className="rounded-2xl border border-line bg-panel p-5"><h2 className="font-serif text-xl">阅读定位</h2><p className="mt-3 text-sm leading-6 text-muted">命中段落会用金色边框标记；后续链接只表示当前快照中已知的显式连接。</p><div className="mt-4 space-y-2">{view.passages.filter((passage, index) => !index || scopeLabel(passage) !== scopeLabel(view.passages[index - 1])).map((passage) => <a key={passage.id} className="block text-sm text-green hover:underline" href={`#${passage.id}`}>{scopeLabel(passage)} · {passage.id}</a>)}</div></div><div className="rounded-2xl border border-line bg-green/5 p-5 text-sm leading-6 text-muted">可读不等于可导出。当前页面只用于核验原创样本文本，不能据此推断真实角色剧情或人物关系。</div><Link className="block text-sm text-green hover:underline" href="/materials">打开素材清单 →</Link></aside></div>}</main>;
}
