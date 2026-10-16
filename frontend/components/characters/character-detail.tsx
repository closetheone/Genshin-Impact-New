"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CharacterPortrait } from "./portrait";
import { DEFAULT_CATALOG, findOfficialLink, type Catalog, type Character, valueLabel } from "./types";

function Facts({ character }: { character: Character }) {
  const facts: Array<[string, string | number | null]> = [["元素", character.element === "无" ? "无固定元素（来源标注）" : character.element], ["武器", character.weapon], ["稀有度", `${character.rarity} 星`], ["地区", character.region], ["所属组织", character.affiliation], ["生日", character.birthday], ["命之座", character.constellation]];
  return <dl className="mt-6 grid gap-3 sm:grid-cols-2">{facts.map(([label, value]) => <div key={label} className="rounded-xl border border-line bg-paper px-4 py-3"><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 font-medium">{valueLabel(value)}</dd></div>)}</dl>;
}

export function CharacterDetailPage({ id: routeId }: { id?: string }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [character, setCharacter] = useState<Character | null>(null);
  const [error, setError] = useState<string | null>(null);
  const returnQuery = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("from") || "";

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const catalogId = params.get("catalog") || DEFAULT_CATALOG;
    const id = routeId ? decodeURIComponent(routeId) : params.get("id") || "";
    const controller = new AbortController();
    fetch(`/api/character-catalog?catalog=${encodeURIComponent(catalogId)}&character=${encodeURIComponent(id)}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "角色资料读取失败"); return data as Catalog & { character?: Character }; })
      .then((data) => { setCatalog(data); setCharacter(data.character || data.characters.find((item) => item.id === id) || null); })
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "角色资料读取失败"); });
    return () => controller.abort();
  }, [routeId]);

  if (error) return <main className="mx-auto min-h-screen max-w-5xl px-5 py-10"><p className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">{error}</p><Link className="mt-5 inline-block text-green hover:underline" href="/characters">← 返回角色目录</Link></main>;
  if (!catalog || !character) return <main className="mx-auto min-h-screen max-w-5xl px-5 py-10"><p className="text-muted">正在读取角色资料…</p></main>;

  const official = findOfficialLink(catalog, character);
  const backHref = returnQuery ? `/characters?${returnQuery}` : "/characters";
  return <main className="mx-auto min-h-screen max-w-6xl px-5 py-10 sm:px-8"><div className="mb-8 flex flex-wrap items-center justify-between gap-3"><Link className="text-sm font-medium text-green hover:underline" href={backHref}>← 返回角色目录</Link><span className="text-xs text-muted">资料批次：{catalog.catalog_id}</span></div><section className="grid gap-8 rounded-3xl border border-line bg-panel p-5 shadow-sm md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] md:p-8"><CharacterPortrait catalog={catalog} character={character} large /><div><p className="text-xs font-semibold uppercase tracking-[0.25em] text-gold">Genshin Impact · character profile</p><h1 className="mt-3 font-serif text-5xl tracking-tight">{character.name}</h1><p className="mt-3 text-muted">{valueLabel(character.region)} · {valueLabel(character.affiliation)}</p><span className="mt-5 inline-flex rounded-full bg-green/10 px-3 py-1 text-sm text-green">角色基础资料 · 社区来源</span><Facts character={character} /></div></section><section className="mt-8 grid gap-5 md:grid-cols-2"><div className="rounded-2xl border border-line bg-panel p-6"><h2 className="font-serif text-2xl">官方角色展示</h2><p className="mt-3 leading-7 text-muted">官网入口可查看官方简介、立绘和配音信息。官网页面内容可能随站点调整。</p>{official ? <a className="mt-5 inline-flex" href={official.url} target="_blank" rel="noreferrer"><Button>前往官网查看{character.name} ↗</Button></a> : <p className="mt-5 text-sm text-muted">尚未匹配到此角色的官网入口。</p>}</div><div className="rounded-2xl border border-line bg-panel p-6"><h2 className="font-serif text-2xl">角色故事</h2><p className="mt-3 leading-7 text-muted">游戏内完整角色故事与对白尚未收录。当前页面只展示已核验的基础资料，不把官网简介扩写成完整故事，也不推断人物关系。</p></div></section><section className="mt-8 rounded-2xl border border-line bg-panel p-6"><h2 className="font-serif text-2xl">资料出处</h2><p className="mt-3 text-sm leading-6 text-muted">数据整理：{catalog.source.name} · 核对日期：{catalog.checked_on}<br />来源范围：{catalog.source.scope}</p><div className="mt-5 flex flex-wrap gap-3"><a href={character.provenance.url} target="_blank" rel="noreferrer"><Button variant="outline">查看此角色来源记录 ↗</Button></a><a href={catalog.source.license_url} target="_blank" rel="noreferrer"><Button variant="outline">仓库许可说明 ↗</Button></a></div><details className="mt-6 rounded-xl bg-paper p-4 text-sm"><summary className="cursor-pointer font-medium">字段定位与核对记录</summary><dl className="mt-4 grid gap-2 sm:grid-cols-2">{Object.entries(character.provenance.fields).map(([field, original]) => <div key={field}><dt className="text-muted">{field}</dt><dd><code>/{original}</code></dd></div>)}</dl><p className="mt-4 break-all text-muted">来源文件 SHA-256：<code>{character.provenance.sha256}</code></p></details></section></main>;
}
