"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { archiveParams, DEFAULT_SNAPSHOT, normalizeScope, predicateLabels, relationScope, speakerName, type GraphView, type Relationship, type RelationshipView } from "./types";

const predicates = ["all", "mentor_of", "parent_of", "opposes", "cooperates_with"];
const conditions = ["all", "opening", "east", "west", "later"];

function nameMap(characters: GraphView["characters"]) {
  const counts = new Map<string, number>();
  characters.forEach((character) => counts.set(character.name, (counts.get(character.name) || 0) + 1));
  return new Map(characters.map((character) => [character.id, counts.get(character.name)! > 1 ? `${character.name} · ${character.id}` : character.name]));
}

function initialState(params: Pick<URLSearchParams, "get">) {
  const hops = Number(params.get("hops"));
  const page = Number(params.get("page"));
  return {
    snapshot: params.get("snapshot") || DEFAULT_SNAPSHOT,
    scope: normalizeScope(params.get("scope")),
    center: params.get("center") || "person:student",
    hops: hops === 2 ? 2 : 1,
    predicate: params.get("predicate") || "all",
    condition: params.get("condition") || "all",
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    cursor: params.get("cursor") || "",
  };
}

function queryString(state: ReturnType<typeof initialState>) {
  const params = new URLSearchParams({ snapshot: state.snapshot, scope: state.scope, purpose: "display", center: state.center, hops: String(state.hops), predicate: state.predicate, condition: state.condition, page: String(state.page) });
  if (state.cursor) params.set("cursor", state.cursor);
  return params.toString();
}

export function GraphPage() {
  const params = useSearchParams();
  const [state, setState] = useState(() => initialState(params));
  const [view, setView] = useState<GraphView | null>(null);
  const [relationship, setRelationship] = useState<RelationshipView | null>(null);
  const [selectedId, setSelectedId] = useState(() => params.get("relation") || "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const request = archiveParams({ snapshot: state.snapshot, scope: state.scope, purpose: "display" });
    request.set("center", state.center);
    request.set("hops", String(state.hops));
    request.set("predicate", state.predicate);
    request.set("condition", state.condition);
    request.set("page", String(state.page));
    if (state.cursor) request.set("cursor", state.cursor);
    fetch(`/api/graph?${request}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "人物关系读取失败"); if (data.dataset_kind !== "synthetic") throw new Error("此页面只接受明确标注的原创合成样本"); return data as GraphView; })
      .then((data) => { setView(data); setError(null); })
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "人物关系读取失败"); });
    return () => controller.abort();
  }, [state]);

  useEffect(() => {
    window.history.replaceState(null, "", `/graph?${queryString(state)}${selectedId ? `&relation=${encodeURIComponent(selectedId)}` : ""}`);
  }, [selectedId, state]);

  const labels = useMemo(() => nameMap(view?.characters || []), [view]);
  const activeRelation = view?.relationships.find((relation) => relation.id === selectedId) || view?.relationships[0] || null;

  const activeRelationId = activeRelation?.id || "";

  useEffect(() => {
    if (!activeRelationId) return;
    const controller = new AbortController();
    const request = archiveParams({ snapshot: state.snapshot, scope: state.scope, purpose: "display" });
    request.set("id", activeRelationId);
    fetch(`/api/relationship?${request}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "关系证据读取失败"); return data as RelationshipView; })
      .then(setRelationship)
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "关系证据读取失败"); });
    return () => controller.abort();
  }, [activeRelationId, state.snapshot, state.scope]);

  function update(field: keyof ReturnType<typeof initialState>, value: string | number) {
    setError(null);
    setState((current) => ({ ...current, [field]: value, page: field === "page" ? Number(value) : 1, cursor: field === "page" ? current.cursor : "" }));
    if (field !== "page") setSelectedId("");
  }

  const selectedRelationship = relationship?.relationships[0]?.id === activeRelationId ? relationship.relationships[0] : null;
  const relation = selectedRelationship || activeRelation;
  const passageById = new Map((relationship?.passages || view?.passages || []).map((passage) => [passage.id, passage]));
  const characterOptions = view?.characters || [];
  const page = view?.pagination.page || state.page;
  const pages = view?.pagination.pages || 1;

  return <main className="mx-auto min-h-screen max-w-7xl px-5 py-10 sm:px-8">
    <header className="mb-8 flex flex-wrap items-end justify-between gap-5"><div><Link href="/" className="text-xs font-semibold uppercase tracking-[0.3em] text-gold">Genshin Impact · archive</Link><h1 className="mt-3 font-serif text-4xl tracking-tight text-ink sm:text-5xl">人物关系图</h1><p className="mt-3 max-w-3xl leading-7 text-muted">关系只在证据支持的范围内展示。当前页面使用原创合成样本；每条关系都可以打开完整证据与原文定位。</p></div><span className="rounded-full bg-green/10 px-3 py-1.5 text-sm text-green" role="status">{view ? `${view.pagination.total_relationships} 条关系` : "读取中"}</span></header>
    <section className="mb-8 rounded-2xl border border-line bg-panel p-4 shadow-sm sm:p-5"><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6"><label className="text-sm font-medium lg:col-span-2">中心人物<select value={state.center} onChange={(event) => update("center", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2">{characterOptions.map((character) => <option key={character.id} value={character.id}>{labels.get(character.id) || character.name}</option>)}</select></label><label className="text-sm font-medium">展开层级<select value={state.hops} onChange={(event) => update("hops", Number(event.target.value))} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="1">一跳关系</option><option value="2">二跳关系</option></select></label><label className="text-sm font-medium">关系类型<select value={state.predicate} onChange={(event) => update("predicate", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2">{predicates.map((predicate) => <option key={predicate} value={predicate}>{predicate === "all" ? "全部类型" : predicateLabels[predicate]}</option>)}</select></label><label className="text-sm font-medium">情节条件<select value={state.condition} onChange={(event) => update("condition", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2">{conditions.map((condition) => <option key={condition} value={condition}>{condition === "all" ? "全部条件" : condition === "opening" ? "开篇公共" : condition === "east" ? "东路分支" : condition === "west" ? "西路分支" : "后续阶段"}</option>)}</select></label><label className="text-sm font-medium">范围<select value={state.scope} onChange={(event) => update("scope", event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2"><option value="all">全部可用范围</option><option value="opening">开篇公共</option><option value="east">东路分支</option><option value="west">西路分支</option><option value="later">后续阶段</option></select></label></div><p className="mt-4 text-xs leading-5 text-muted">当前快照 <code>{state.snapshot}</code> · 展开 {state.hops} 跳 · 页面只展示原创测试资料。</p></section>
    {error ? <div className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800"><p>{error}</p><button className="mt-2 text-sm font-medium underline" onClick={() => setState((current) => ({ ...current, cursor: "" }))}>重新读取第一页</button></div> : null}
    {!view && !error ? <p className="text-muted">正在读取关系与证据…</p> : null}
    {view ? <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]"><section><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-serif text-2xl">当前关系列表</h2><p className="mt-1 text-sm text-muted">{view.characters.length} 位人物 · {view.relationships.length} 条当前页关系</p></div>{view.truncated ? <span className="rounded-full bg-gold/15 px-3 py-1 text-xs text-ink">当前结果已截断</span> : null}</div><div className="space-y-3">{view.relationships.map((item) => <button key={item.id} type="button" onClick={() => { setSelectedId(item.id); window.history.replaceState(null, "", `/graph?${queryString(state)}&relation=${encodeURIComponent(item.id)}`); }} className={`w-full rounded-2xl border p-5 text-left transition ${item.id === relation?.id ? "border-green bg-green/5 shadow-sm" : "border-line bg-panel hover:border-green/50"}`} aria-pressed={item.id === relation?.id}><div className="flex flex-wrap items-center gap-2 text-xs text-muted"><span className="rounded-full bg-green/10 px-2 py-1 text-green">{predicateLabels[item.predicate] || item.predicate}</span><span>{relationScope(item)}</span><span>{item.review_status === "approved" ? "已核验" : item.review_status}</span></div><h3 className="mt-3 font-serif text-xl">{labels.get(item.from_id) || item.from_id} <span className="text-muted">{item.direction === "directed" ? "→" : "—"}</span> {labels.get(item.to_id) || item.to_id}</h3><p className="mt-2 text-sm leading-6 text-muted">{item.description}</p></button>)}</div>{!view.relationships.length ? <div className="rounded-2xl border border-dashed border-line bg-panel p-10 text-center text-muted">当前条件下没有可用关系。可以切换中心人物、范围或情节条件。</div> : null}<nav className="mt-8 flex items-center justify-center gap-4" aria-label="关系分页"><Button variant="outline" disabled={!view.pagination.previous_cursor} onClick={() => setState((current) => ({ ...current, cursor: view.pagination.previous_cursor || "" }))}>上一页</Button><span className="text-sm text-muted">第 {page} / {pages} 页</span><Button variant="outline" disabled={!view.pagination.next_cursor} onClick={() => setState((current) => ({ ...current, cursor: view.pagination.next_cursor || "" }))}>下一页</Button></nav></section><aside className="space-y-4"><div className="rounded-2xl border border-line bg-panel p-5"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-gold">Evidence panel</p>{relation ? <><h2 className="mt-3 font-serif text-2xl">{labels.get(relation.from_id) || relation.from_id} {relation.direction === "directed" ? "→" : "—"} {labels.get(relation.to_id) || relation.to_id}</h2><p className="mt-2 text-sm text-muted">{predicateLabels[relation.predicate] || relation.predicate} · {relationScope(relation)}</p><p className="mt-4 leading-7">{relation.description}</p><div className="mt-5 space-y-4">{relation.evidence_groups.map((group, index) => <div key={`${relation.id}-${index}`} className="rounded-xl bg-paper p-4"><p className="text-xs font-medium text-muted">证据组 {index + 1}</p><div className="mt-3 space-y-3">{group.map((passageId) => { const passage = passageById.get(passageId); return passage ? <blockquote key={passageId} className="border-l-2 border-gold pl-3 text-sm leading-6"><p>{passage.text}</p><footer className="mt-2 text-xs text-muted">{speakerName(relationship?.characters || view.characters, passage.speaker_id)} · <Link className="text-green hover:underline" href={`/read?passage=${encodeURIComponent(passage.id)}&snapshot=${encodeURIComponent(state.snapshot)}&scope=${encodeURIComponent(state.scope)}&purpose=display`}>{passage.id} · 回到原文 ↗</Link><br /><code>{passage.source_id} · {passage.source_locator}</code></footer></blockquote> : <p key={passageId} className="text-sm text-muted">{passageId}：当前范围未提供这段证据。</p>; })}</div></div>)}</div><details className="mt-5 rounded-xl bg-paper p-4 text-sm"><summary className="cursor-pointer font-medium">关系核验字段</summary><dl className="mt-3 grid gap-2"><div><dt className="text-muted">关系 ID</dt><dd><code>{relation.id}</code></dd></div><div><dt className="text-muted">声明类型</dt><dd>{relation.claim_kind}</dd></div><div><dt className="text-muted">来源</dt><dd><code>{relation.source_id}</code></dd></div></dl></details></> : <p className="mt-3 text-muted">选择一条关系查看证据。</p>}</div><div className="rounded-2xl border border-line bg-green/5 p-5 text-sm leading-6 text-muted">这里的“关系”必须能回到明确原文证据；同场出现不会自动生成关系，分支条件也不会被合并成同一时刻。</div></aside></div> : null}
  </main>;
}
