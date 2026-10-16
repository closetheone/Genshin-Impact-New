"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { archiveParams, DEFAULT_SNAPSHOT, normalizeScope, scopeLabel, speakerName, type SearchView } from "./types";
import { addPassageToLocalSelection } from "./materials-client";

type SearchState = {
  q: string;
  mode: "literal" | "keywords";
  category: string;
  speaker: string;
  limit: number;
  scope: string;
  snapshot: string;
  cursor: string;
};

function initialState(params: Pick<URLSearchParams, "get">): SearchState {
  const limit = Number(params.get("limit"));
  return {
    q: (params.get("q") || "").slice(0, 200),
    mode: params.get("mode") === "keywords" ? "keywords" : "literal",
    category: params.get("category") || "all",
    speaker: params.get("speaker") || "all",
    limit: [8, 16, 32].includes(limit) ? limit : 8,
    scope: normalizeScope(params.get("scope")),
    snapshot: params.get("snapshot") || DEFAULT_SNAPSHOT,
    cursor: params.get("cursor") || "",
  };
}

function highlight(text: string, query: string, mode: SearchState["mode"]) {
  const terms = mode === "keywords" ? query.trim().split(/\s+/u).filter(Boolean) : [query.trim()];
  const pattern = terms.filter(Boolean).map((term) => term.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")).join("|");
  if (!pattern) return text;
  return text.split(new RegExp(`(${pattern})`, "giu")).map((part, index) => new RegExp(`^(?:${pattern})$`, "iu").test(part) ? <mark key={`${part}-${index}`} className="rounded bg-gold/20 px-0.5 text-ink">{part}</mark> : <span key={`${part}-${index}`}>{part}</span>);
}

function queryString(state: SearchState) {
  const params = new URLSearchParams({ snapshot: state.snapshot, scope: state.scope, purpose: "display", mode: state.mode, category: state.category, speaker: state.speaker, limit: String(state.limit) });
  if (state.q) params.set("q", state.q);
  if (state.cursor) params.set("cursor", state.cursor);
  return params.toString();
}

export function SearchPage() {
  const params = useSearchParams();
  const [state, setState] = useState(() => initialState(params));
  const [draftQuery, setDraftQuery] = useState(() => initialState(params).q);
  const [view, setView] = useState<SearchView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const request = new URLSearchParams(archiveParams(state));
    request.set("q", state.q);
    request.set("mode", state.mode);
    request.set("category", state.category);
    request.set("speaker", state.speaker);
    request.set("limit", String(state.limit));
    if (state.cursor) request.set("cursor", state.cursor);
    fetch(`/api/search?${request}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "文本检索失败"); if (data.dataset_kind !== "synthetic") throw new Error("此页面只接受明确标注的原创合成样本"); return data as SearchView; })
      .then(setView)
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "文本检索失败"); });
    const url = `/search?${queryString(state)}`;
    window.history.replaceState(null, "", url);
    return () => controller.abort();
  }, [state]);

  const entryTitles = useMemo(() => new Map((view?.entries || []).map((entry) => [entry.id, entry.title])), [view]);
  const speakerOptions = view?.facets.speakers || [];
  const categoryOptions = view?.facets.categories || [];

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setState((current) => ({ ...current, q: draftQuery, cursor: "" }));
  }

  function updateFilter(field: "mode" | "category" | "speaker" | "limit" | "scope", value: string) {
    setError(null);
    setState((current) => ({ ...current, [field]: field === "limit" ? Number(value) : value, cursor: "" } as SearchState));
  }

  function reset() {
    setDraftQuery("");
    setState((current) => ({ ...current, q: "", mode: "literal", category: "all", speaker: "all", scope: "all", cursor: "" }));
  }

  const page = view?.pagination.page || (view ? Math.floor(view.pagination.offset / view.pagination.limit) + 1 : 1);
  const pages = view?.pagination.pages || Math.max(1, Math.ceil((view?.pagination.total || 0) / (view?.pagination.limit || state.limit)));
  const fromQuery = queryString({ ...state, cursor: "" });

  return <main className="mx-auto min-h-screen max-w-7xl px-5 py-10 sm:px-8">
    <header className="mb-8 flex flex-wrap items-end justify-between gap-5"><div><Link href="/" className="text-xs font-semibold uppercase tracking-[0.3em] text-gold">Genshin Impact · archive</Link><h1 className="mt-3 font-serif text-4xl tracking-tight text-ink sm:text-5xl">文本检索</h1><p className="mt-3 max-w-2xl leading-7 text-muted">在当前快照与范围内查找原创样本文本。每个命中位置都能回到完整上下文，搜索结果不会替代原文核验。</p></div><span className="rounded-full bg-green/10 px-3 py-1.5 text-sm text-green" role="status">{view ? `${view.pagination.total} 个独立出现位置` : "读取中"}</span></header>
    <section className="mb-8 rounded-2xl border border-line bg-panel p-4 shadow-sm sm:p-5"><form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row"><label className="sr-only" htmlFor="archive-search-input">搜索原创样本文本</label><input id="archive-search-input" value={draftQuery} onChange={(event) => setDraftQuery(event.target.value.slice(0, 200))} placeholder="输入关键词或一句对白…" className="h-11 min-w-0 flex-1 rounded-lg border border-line bg-paper px-3 outline-none focus:border-green focus:ring-2 focus:ring-green/20" /><Button type="submit">检索</Button><Button type="button" variant="outline" onClick={reset}>清空</Button></form><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><label className="text-sm font-medium">匹配方式<select value={state.mode} onChange={(event) => updateFilter("mode", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="literal">原句包含</option><option value="keywords">关键词同时包含</option></select></label><label className="text-sm font-medium">范围<select value={state.scope} onChange={(event) => updateFilter("scope", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="all">全部可用范围</option><option value="opening">开篇公共</option><option value="east">东路分支</option><option value="west">西路分支</option><option value="later">后续阶段</option></select></label><label className="text-sm font-medium">分类<select value={state.category} onChange={(event) => updateFilter("category", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="all">全部分类</option>{categoryOptions.map((item) => <option key={item.value} value={item.value}>{item.value} · {item.count}</option>)}</select></label><label className="text-sm font-medium">说话人<select value={state.speaker} onChange={(event) => updateFilter("speaker", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="all">全部说话人</option>{speakerOptions.map((item) => <option key={item.value} value={item.value}>{item.value === "narration" ? "叙述" : speakerName(view?.characters || [], item.value)} · {item.count}</option>)}</select></label><label className="text-sm font-medium">每页<select value={state.limit} onChange={(event) => updateFilter("limit", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="8">8 条</option><option value="16">16 条</option><option value="32">32 条</option></select></label></div><p className="mt-4 text-xs leading-5 text-muted">当前使用快照 <code>{state.snapshot}</code> · 页面仅展示原创合成测试数据，不代表原神剧情。</p></section>
    {error ? <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><p>{error}</p><button className="mt-2 text-sm font-medium underline" onClick={() => setState((current) => ({ ...current, cursor: "" }))}>从第一页重新检索</button></div> : null}
    {!view && !error ? <p className="text-muted">正在按当前范围与用途打开档案…</p> : null}
    {notice ? <p className="mb-4 rounded-lg bg-green/10 p-3 text-sm text-green" role="status">{notice}</p> : null}
    {view ? <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]"><section aria-label="搜索结果"><div className="mb-4 flex items-center justify-between gap-3"><h2 className="font-serif text-2xl">{state.q ? "检索结果" : "浏览文本"}</h2><span className="text-sm text-muted">本页 {view.results.length} 条 · 第 {page} / {pages} 页</span></div><div className="space-y-4">{view.results.map((passage) => { const readParams = new URLSearchParams({ passage: passage.id, ...Object.fromEntries(new URLSearchParams(fromQuery)) }); return <article key={passage.id} className="rounded-2xl border border-line bg-panel p-5 shadow-sm"><div className="flex flex-wrap items-center gap-2 text-xs text-muted"><span className="rounded-full bg-green/10 px-2 py-1 text-green">{scopeLabel(passage)}</span><span>{entryTitles.get(passage.entry_id) || passage.entry_id}</span></div><Link href={`/read?${readParams}`} className="mt-3 block text-lg leading-8 text-ink hover:text-green">{highlight(passage.text, state.q, state.mode)}</Link><div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-muted"><span>{speakerName(view.characters, passage.speaker_id)} · <code>{passage.id}</code></span><div className="flex flex-wrap gap-3"><button type="button" className="text-green hover:underline" onClick={() => { try { addPassageToLocalSelection(passage.id, view.snapshot_id); setNotice(`已加入 ${passage.id}，请到素材清单重新核验。`); } catch (reason) { setNotice(reason instanceof Error ? reason.message : "加入素材失败"); } }}>加入素材 ＋</button><Link className="font-medium text-green hover:underline" href={`/read?${readParams}`}>回到原文 ↗</Link></div></div></article>; })}</div>{!view.results.length ? <div className="rounded-2xl border border-dashed border-line bg-panel p-10 text-center text-muted">没有符合当前条件的文本。</div> : null}<nav className="mt-8 flex items-center justify-center gap-4" aria-label="搜索结果分页"><Button variant="outline" disabled={!view.pagination.previous_cursor} onClick={() => setState((current) => ({ ...current, cursor: view.pagination.previous_cursor || "" }))}>← 上一页</Button><span className="text-sm text-muted">第 {page} / {pages} 页</span><Button variant="outline" disabled={!view.pagination.next_cursor} onClick={() => setState((current) => ({ ...current, cursor: view.pagination.next_cursor || "" }))}>下一页 →</Button></nav></section><aside className="space-y-4"><div className="rounded-2xl border border-line bg-green/5 p-5"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-gold">Current page archive</p><h3 className="mt-3 font-serif text-xl">{view.entries[0]?.title || "当前范围"}</h3><p className="mt-3 text-sm leading-6 text-muted">共 {view.stats.passages} 段文本、{view.stats.characters} 位人物。沿着原文入口核验命中位置，再判断人物关系。</p></div><div className="rounded-2xl border border-line bg-panel p-5"><h3 className="font-serif text-xl">继续探索</h3><div className="mt-4 space-y-3 text-sm"><Link className="block text-green hover:underline" href={`/characters?catalog=genshin-basics-2026-10-15-v2`}>查看真实角色目录 →</Link><Link className="block text-green hover:underline" href={`/graph?snapshot=${encodeURIComponent(state.snapshot)}&scope=${encodeURIComponent(state.scope)}&purpose=display`}>探索原创人物关系图 →</Link><Link className="block text-green hover:underline" href="/materials">打开素材清单 →</Link></div></div></aside></div> : null}
  </main>;
}
