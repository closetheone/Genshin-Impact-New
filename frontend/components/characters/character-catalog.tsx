"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { CharacterPortrait } from "./portrait";
import { DEFAULT_CATALOG, findOfficialLink, type Catalog, type Character, valueLabel } from "./types";

const PAGE_SIZE = 24;

function readSelection() {
  if (typeof window === "undefined") return { query: "", element: "all", region: "all", sort: "default" as const, page: 1, catalog: DEFAULT_CATALOG };
  const params = new URLSearchParams(window.location.search);
  const page = Number(params.get("page"));
  const sortParam = params.get("sort");
  return {
    query: (params.get("q") || "").slice(0, 160),
    element: params.get("element") || "all",
    region: params.get("region") || "all",
    sort: sortParam === "name" || sortParam === "rarity" ? sortParam : "default",
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    catalog: params.get("catalog") || DEFAULT_CATALOG,
  };
}

function updateUrl(selection: { query: string; element: string; region: string; sort: string; page: number; catalog: string }) {
  const params = new URLSearchParams({ catalog: selection.catalog });
  if (selection.query) params.set("q", selection.query);
  if (selection.element !== "all") params.set("element", selection.element);
  if (selection.region !== "all") params.set("region", selection.region);
  if (selection.sort !== "default") params.set("sort", selection.sort);
  if (selection.page > 1) params.set("page", String(selection.page));
  window.history.replaceState(null, "", `${window.location.pathname}?${params}`);
}

function matches(character: Character, query: string, element: string, region: string) {
  if (element !== "all" && character.element !== element) return false;
  if (region !== "all" && (region === "missing" ? character.region : character.region !== region)) return false;
  const term = query.trim().toLocaleLowerCase();
  return !term || [character.name, character.region, character.affiliation, character.weapon, character.slug]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase()
    .includes(term);
}

export function CharacterCatalogPage() {
  const [selection, setSelection] = useState(readSelection);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/character-catalog?catalog=${encodeURIComponent(selection.catalog)}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "角色目录读取失败");
        if (data.dataset_kind !== "real_character_facts") throw new Error("资料类型不匹配，未替换为样本");
        return data as Catalog;
      })
      .then(setCatalog)
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "角色目录读取失败"); });
    return () => controller.abort();
  }, [selection.catalog]);

  const elements = useMemo(() => [...new Set(catalog?.characters.map((character) => character.element) || [])], [catalog]);
  const regions = useMemo(() => [...new Set(catalog?.characters.map((character) => character.region).filter((region): region is string => Boolean(region)) || [])], [catalog]);
  const filtered = useMemo(() => {
    const records = catalog?.characters.filter((character) => matches(character, selection.query, selection.element, selection.region)) || [];
    return records.sort((left, right) => {
      if (selection.sort === "name") return left.name.localeCompare(right.name, "zh-CN");
      if (selection.sort === "rarity") return right.rarity - left.rarity || left.name.localeCompare(right.name, "zh-CN");
      return 0;
    });
  }, [catalog, selection]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const page = Math.min(selection.page, pages);
  const records = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  useEffect(() => {
    updateUrl({ ...selection, page });
  }, [page, selection]);

  const changeSelection = (patch: Partial<typeof selection>) => setSelection((current) => ({ ...current, ...patch, page: patch.page ?? 1 }));

  return (
    <main className="mx-auto min-h-screen max-w-7xl px-5 py-10 sm:px-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-5">
        <div>
          <Link href="/" className="text-xs font-semibold uppercase tracking-[0.3em] text-gold">Genshin Impact · archive</Link>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-ink sm:text-5xl">原神角色资料目录</h1>
          <p className="mt-3 max-w-2xl leading-7 text-muted">固定来源目录中的角色基础资料。官网立绘和简介入口独立标注，未收录的故事字段不会由页面推测补齐。</p>
        </div>
        <span className="rounded-full bg-green/10 px-3 py-1.5 text-sm text-green" role="status">{catalog ? `${filtered.length} / ${catalog.characters.length} 条记录` : "读取中"}</span>
      </header>

      <section className="mb-8 rounded-2xl border border-line bg-panel p-4 shadow-sm sm:p-5" aria-label="角色筛选">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_160px_160px_160px_auto]">
          <label className="text-sm font-medium text-ink">查找角色<input value={selection.query} onChange={(event) => changeSelection({ query: event.target.value.slice(0, 160) })} placeholder="角色名、武器、地区或组织" className="mt-1.5 h-11 w-full rounded-lg border border-line bg-paper px-3 outline-none transition focus:border-green focus:ring-2 focus:ring-green/20" /></label>
          <label className="text-sm font-medium text-ink">元素<select value={selection.element} onChange={(event) => changeSelection({ element: event.target.value })} className="mt-1.5 h-11 w-full rounded-lg border border-line bg-paper px-3 outline-none focus:border-green"><option value="all">全部元素</option>{elements.map((element) => <option key={element} value={element}>{element === "无" ? "无固定元素" : element}</option>)}</select></label>
          <label className="text-sm font-medium text-ink">地区<select value={selection.region} onChange={(event) => changeSelection({ region: event.target.value })} className="mt-1.5 h-11 w-full rounded-lg border border-line bg-paper px-3 outline-none focus:border-green"><option value="all">全部地区</option>{regions.map((region) => <option key={region} value={region}>{region}</option>)}<option value="missing">来源未提供</option></select></label>
          <label className="text-sm font-medium text-ink">排序<select value={selection.sort} onChange={(event) => changeSelection({ sort: event.target.value })} className="mt-1.5 h-11 w-full rounded-lg border border-line bg-paper px-3 outline-none focus:border-green"><option value="default">默认顺序</option><option value="name">名称</option><option value="rarity">稀有度</option></select></label>
          <Button variant="outline" className="self-end" onClick={() => changeSelection({ query: "", element: "all", region: "all", sort: "default" })}>重置筛选</Button>
        </div>
      </section>

      {error ? <p className="mb-6 rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">{error}。请先启动 Python 服务：<code>python3 scripts/serve_prototype.py --port 4175</code></p> : null}
      {!catalog && !error ? <p className="text-muted">正在读取本地 Python API…</p> : null}
      {catalog ? <>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {records.map((character) => {
            const official = findOfficialLink(catalog, character);
            const returnParams = new URLSearchParams({ catalog: catalog.catalog_id });
            if (selection.query) returnParams.set("q", selection.query);
            if (selection.element !== "all") returnParams.set("element", selection.element);
            if (selection.region !== "all") returnParams.set("region", selection.region);
            if (selection.sort !== "default") returnParams.set("sort", selection.sort);
            if (page > 1) returnParams.set("page", String(page));
            const detailHref = `/characters/${encodeURIComponent(character.id)}?catalog=${encodeURIComponent(catalog.catalog_id)}&from=${encodeURIComponent(returnParams.toString())}`;
            return <article key={character.id} className="group overflow-hidden rounded-2xl border border-line bg-panel shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
              <Link href={detailHref} aria-label={`查看${character.name}详情`}><CharacterPortrait catalog={catalog} character={character} /></Link>
              <div className="p-4"><div className="flex items-center justify-between gap-2 text-xs text-muted"><span>{valueLabel(character.region)}</span><span>{character.rarity} 星</span></div><h2 className="mt-1 font-serif text-2xl"><Link href={detailHref}>{character.name}</Link></h2><p className="mt-2 text-sm text-muted">{character.element} · {character.weapon}</p><div className="mt-4 flex flex-wrap items-center gap-3 text-xs"><Link className="font-medium text-green hover:underline" href={detailHref}>基本资料与出处 →</Link>{official ? <a className="text-muted hover:text-green hover:underline" href={official.url} target="_blank" rel="noreferrer">官网简介 ↗</a> : <span className="text-muted">官网入口未匹配</span>}</div></div>
            </article>;
          })}
        </div>
        {!records.length ? <div className="rounded-2xl border border-dashed border-line bg-panel p-10 text-center text-muted">没有符合筛选条件的角色。</div> : null}
        <nav className="mt-8 flex items-center justify-center gap-4" aria-label="角色目录分页"><Button variant="outline" disabled={page === 1} onClick={() => changeSelection({ page: page - 1 })}>上一页</Button><span className="text-sm text-muted">第 {page} / {pages} 页</span><Button variant="outline" disabled={page === pages} onClick={() => changeSelection({ page: page + 1 })}>下一页</Button></nav>
        <footer className="mt-10 rounded-2xl border border-line bg-green/5 p-5 text-sm leading-6 text-muted">已收录固定来源目录的全部 {catalog.coverage?.record_count ?? catalog.characters.length} 条角色记录；当前匹配 {catalog.official_art?.records.length ?? 0} 组官网图片。资料整理：{catalog.source.name} · 核对日期：{catalog.checked_on}。<Link className="ml-1 text-green hover:underline" href={`/real-characters?catalog=${encodeURIComponent(catalog.catalog_id)}`}>查看兼容目录入口 →</Link></footer>
      </> : null}
    </main>
  );
}
