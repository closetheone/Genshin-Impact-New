"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CharacterPortrait } from "./portrait";
import { characterCompleteness, DEFAULT_CATALOG, findArt, findOfficialLink, type Catalog, type Character, valueLabel } from "./types";

function Facts({ character }: { character: Character }) {
  const groups: Array<{ title: string; facts: Array<[string, string | number | null]> }> = [
    {
      title: "战斗属性",
      facts: [["元素", character.element === "无" ? "无固定元素（来源标注）" : character.element], ["武器", character.weapon], ["稀有度", `${character.rarity} 星`]],
    },
    {
      title: "世界身份",
      facts: [["地区", character.region], ["所属组织", character.affiliation], ["命之座", character.constellation]],
    },
    { title: "基础信息", facts: [["生日", character.birthday]] },
  ];
  return <div className="mt-6 space-y-5">{groups.map((group) => <section key={group.title} aria-labelledby={`facts-${group.title}`}><h2 id={`facts-${group.title}`} className="text-sm font-semibold text-ink">{group.title}</h2><dl className="mt-2 grid gap-3 sm:grid-cols-2">{group.facts.map(([label, value]) => <div key={label} className="rounded-xl border border-line bg-paper px-4 py-3"><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 font-medium">{valueLabel(value)}</dd></div>)}</dl></section>)}</div>;
}

function CompletenessSummary({ character }: { character: Character }) {
  const completeness = characterCompleteness(character);
  const percentage = Math.round((completeness.available / completeness.total) * 100);
  return <section className="mt-6 rounded-xl border border-line bg-paper p-4" aria-labelledby="completeness-title"><div className="flex items-center justify-between gap-3"><h2 id="completeness-title" className="text-sm font-semibold text-ink">基础资料完整度</h2><span className="text-sm font-medium text-green">{percentage}%</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-label="基础资料完整度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percentage}><div className="h-full rounded-full bg-green transition-all" style={{ width: `${percentage}%` }} /></div><p className="mt-3 text-xs leading-5 text-muted">已提供 {completeness.available}/{completeness.total} 个基础字段{completeness.missing.length ? `；缺少：${completeness.missing.join("、")}` : "，当前字段均有来源值"}。</p></section>;
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
  const art = findArt(catalog, character);
  const completeness = characterCompleteness(character);
  const backHref = returnQuery ? `/characters?${returnQuery}` : "/characters";
  const related = catalog.characters
    .filter((item) => item.id !== character.id && ((character.region && item.region === character.region) || (character.affiliation && item.affiliation === character.affiliation)))
    .slice(0, 6);
  return <main className="mx-auto min-h-screen max-w-6xl px-5 py-10 sm:px-8"><div className="mb-8 flex flex-wrap items-center justify-between gap-3"><Link className="text-sm font-medium text-green hover:underline" href={backHref}>← 返回角色目录</Link><span className="text-xs text-muted">资料批次：{catalog.catalog_id}</span></div><section className="grid gap-8 rounded-3xl border border-line bg-panel p-5 shadow-sm md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] md:p-8"><CharacterPortrait catalog={catalog} character={character} large /><div><p className="text-xs font-semibold uppercase tracking-[0.25em] text-gold">Genshin Impact · character profile</p><h1 className="mt-3 font-serif text-5xl tracking-tight">{character.name}</h1><p className="mt-3 text-muted">{valueLabel(character.region)} · {valueLabel(character.affiliation)}</p><span className="mt-5 inline-flex rounded-full bg-green/10 px-3 py-1 text-sm text-green">角色基础资料 · 社区来源</span><CompletenessSummary character={character} /><Facts character={character} /></div></section><section className="mt-8 grid gap-5 md:grid-cols-2"><div className="rounded-2xl border border-line bg-panel p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-serif text-2xl">官方角色展示</h2><p className="mt-3 leading-7 text-muted">官网入口可查看官方简介、立绘和配音信息。官网页面内容可能随站点调整。</p></div><span className={`rounded-full px-2.5 py-1 text-xs ${official ? "bg-green/10 text-green" : "bg-gold/15 text-ink"}`}>{official ? "已匹配官网入口" : "入口待匹配"}</span></div>{art ? <p className="mt-4 text-sm text-muted">当前已匹配官网图片，可从页面顶部查看；图片来源记录：<a className="text-green hover:underline" href={art.source_url} target="_blank" rel="noreferrer">打开图片来源 ↗</a></p> : <p className="mt-4 text-sm text-muted">当前没有匹配到官网图片，页面使用文字占位；如需核对立绘，请从官网入口查看。</p>}{official ? <a className="mt-5 inline-flex" href={official.url} target="_blank" rel="noreferrer"><Button>前往官网查看{character.name} ↗</Button></a> : <p className="mt-5 text-sm text-muted">尚未匹配到此角色的官网入口。</p>}</div><div className="rounded-2xl border border-line bg-panel p-6" aria-labelledby="story-status-title"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 id="story-status-title" className="font-serif text-2xl">角色故事</h2><p className="mt-2 text-sm font-medium text-gold">当前状态：尚未接入真实故事正文</p></div><span className="rounded-full bg-gold/15 px-2.5 py-1 text-xs text-ink">待准入</span></div><p className="mt-3 leading-7 text-muted">当前批次只核验角色基础字段、字段出处和官网入口，不包含角色故事、对白或人物关系。官网简介可以作为外部参考入口，但不会在这里扩写成完整故事。</p><dl className="mt-5 grid gap-2 text-sm sm:grid-cols-2"><div className="rounded-lg bg-paper p-3"><dt className="text-muted">当前可展示</dt><dd className="mt-1 font-medium">基础资料、官网立绘、官网入口</dd></div><div className="rounded-lg bg-paper p-3"><dt className="text-muted">待补数据</dt><dd className="mt-1 font-medium">故事正文、对白、关系证据</dd></div></dl><Link className="mt-5 inline-block text-sm font-medium text-green hover:underline" href="/about#source-admission">查看真实来源准入条件 →</Link></div></section>{related.length ? <section className="mt-8 rounded-2xl border border-line bg-panel p-6" aria-labelledby="related-characters-title"><div className="flex flex-wrap items-end justify-between gap-3"><div><h2 id="related-characters-title" className="font-serif text-2xl">继续浏览角色资料</h2><p className="mt-2 text-sm leading-6 text-muted">以下角色与当前角色共享来源中的地区或所属组织字段，仅用于资料导航，不代表已核验的人物关系。</p></div><Link className="text-sm font-medium text-green hover:underline" href={`/characters?catalog=${encodeURIComponent(catalog.catalog_id)}`}>返回角色目录 →</Link></div><div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{related.map((item) => { const sharedRegion = Boolean(character.region && item.region === character.region); const href = `/characters/${encodeURIComponent(item.id)}?catalog=${encodeURIComponent(catalog.catalog_id)}`; return <article key={item.id} className="flex gap-3 rounded-xl border border-line bg-paper p-3"><Link href={href} className="block w-20 shrink-0" aria-label={`查看${item.name}详情`}><CharacterPortrait catalog={catalog} character={item} /></Link><div className="min-w-0"><h3 className="font-serif text-lg"><Link href={href} className="hover:text-green">{item.name}</Link></h3><p className="mt-1 text-xs text-muted">{sharedRegion ? `同地区 · ${valueLabel(item.region)}` : `同组织 · ${valueLabel(item.affiliation)}`}</p><p className="mt-2 text-xs text-muted">{item.element} · {item.weapon}</p></div></article>; })}</div></section> : null}<section className="mt-8 rounded-2xl border border-line bg-panel p-6"><h2 className="font-serif text-2xl">资料出处</h2><p className="mt-3 text-sm leading-6 text-muted">数据整理：{catalog.source.name} · 核对日期：{catalog.checked_on}<br />来源范围：{catalog.source.scope}</p><div className="mt-5 flex flex-wrap gap-3"><a href={character.provenance.url} target="_blank" rel="noreferrer"><Button variant="outline">查看此角色来源记录 ↗</Button></a><a href={catalog.source.license_url} target="_blank" rel="noreferrer"><Button variant="outline">仓库许可说明 ↗</Button></a></div><details className="mt-6 rounded-xl bg-paper p-4 text-sm"><summary className="cursor-pointer font-medium">字段定位与核对记录</summary><dl className="mt-4 grid gap-2 sm:grid-cols-2">{Object.entries(character.provenance.fields).map(([field, original]) => <div key={field}><dt className="text-muted">{field}</dt><dd><code>/{original}</code></dd></div>)}</dl><p className="mt-4 break-all text-muted">来源文件 SHA-256：<code>{character.provenance.sha256}</code></p></details></section></main>;
}
