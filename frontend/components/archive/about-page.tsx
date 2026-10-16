"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { archiveParams, DEFAULT_SNAPSHOT, type StatusView } from "./types";

const kinds = { text: "文本错误", attribution: "归属错误", branch: "分支问题", relationship: "人物关系错误", missing: "内容缺漏", usage: "内容使用问题" };

export function AboutPage() {
  const [status, setStatus] = useState<StatusView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("text");
  const [snapshot, setSnapshot] = useState(DEFAULT_SNAPSHOT);
  const [reference, setReference] = useState("");
  const [description, setDescription] = useState("");
  const [contact, setContact] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const request = archiveParams({ snapshot: DEFAULT_SNAPSHOT, scope: "all", purpose: "display" });
    fetch(`/api/status?${request}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.error || "收录状态读取失败"); return data as StatusView; })
      .then((data) => { setStatus(data); setSnapshot(data.snapshot_id); })
      .catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "收录状态读取失败"); });
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    const payload = { request_id: crypto.randomUUID(), kind, snapshot, reference, description, contact };
    try { const response = await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), cache: "no-store" }); const data = await response.json(); if (!response.ok) throw new Error(data.error || "反馈提交失败"); setMessage(`已保存至本地维护收件箱。编号：${data.id}`); setDescription(""); setContact(""); }
    catch (reason: unknown) { setMessage(reason instanceof Error ? `${reason.message} 说明仍保留，可重试。` : "反馈提交失败，说明仍保留，可重试。"); }
    finally { setBusy(false); }
  }

  const admissionSources = status?.source_admission?.sources || [];

  return <main className="mx-auto min-h-screen max-w-6xl px-5 py-10 sm:px-8"><header className="mb-8"><Link href="/" className="text-xs font-semibold uppercase tracking-[0.3em] text-gold">Genshin Impact · archive</Link><h1 className="mt-3 font-serif text-4xl tracking-tight text-ink sm:text-5xl">收录与纠错</h1><p className="mt-3 max-w-3xl leading-7 text-muted">这里说明当前收录范围、来源准入状态和已知缺口。纠错反馈只写入本机维护收件箱，不会公开发布。</p></header><div className="space-y-6"><section className="rounded-2xl border border-line bg-green/5 p-5"><h2 className="font-serif text-2xl">当前数据边界</h2><p className="mt-3 leading-7">剧情检索、原文阅读和人物关系图使用原创合成测试数据，不是原神剧情。真实角色目录使用固定版本的社区基础资料，提供字段出处与许可链接；官网立绘仅保留已核对的在线入口。完整真实剧情和人物关系尚未接入。</p><p className="mt-3 text-sm text-muted">当前快照：<code>{status?.snapshot_id || snapshot}</code> · 页面不会自动切换到其他快照。</p><div className="mt-4 flex flex-wrap gap-3"><Link href="/characters"><Button>查看角色目录</Button></Link><Link href="/search"><Button variant="outline">查看原创文本检索</Button></Link><Link href="/graph"><Button variant="outline">查看关系图</Button></Link></div></section><section id="source-admission" className="scroll-mt-24 rounded-2xl border border-line bg-panel p-5"><h2 className="font-serif text-2xl">真实来源准入状态</h2>{error ? <p className="mt-4 rounded-lg bg-red-50 p-3 text-red-800">{error}</p> : admissionSources.length ? admissionSources.map((source) => <article key={source.source_id} className="mt-4 rounded-xl border border-line bg-paper p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-medium">{source.source_id}</h3><span className={`rounded-full px-2 py-1 text-xs ${source.ready ? "bg-green/10 text-green" : "bg-gold/15 text-ink"}`}>{source.ready ? "已准入" : "待确认"}</span></div><p className="mt-2 text-sm text-muted">申请用途：{source.requested_uses.join("、")} · 页面数：{source.page_count}</p>{!source.ready ? <><p className="mt-3 text-sm">待补字段：{source.missing_requirements.join("、")}</p><ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-muted">{source.next_actions.slice(0, 4).map((action) => <li key={action}>{action}</li>)}</ol></> : <p className="mt-3 text-sm text-green">授权字段已满足当前申请用途。</p>}</article>) : <p className="mt-4 text-muted">准入状态暂不可用。</p>}</section><section className="rounded-2xl border border-line bg-panel p-5"><h2 className="font-serif text-2xl">提交纠错</h2><p className="mt-3 text-sm leading-6 text-muted">请提供可定位的快照、段落或关系 ID。联系信息可留空。</p><form onSubmit={submit} className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium">问题类型<select value={kind} onChange={(event) => setKind(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2">{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="text-sm font-medium">相关快照<input value={snapshot} onChange={(event) => setSnapshot(event.target.value.slice(0, 160))} maxLength={160} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2" /></label><label className="text-sm font-medium sm:col-span-2">段落 / 关系 ID（可选）<input value={reference} onChange={(event) => setReference(event.target.value.slice(0, 160))} maxLength={160} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2" /></label><label className="text-sm font-medium sm:col-span-2">问题说明<textarea required value={description} onChange={(event) => setDescription(event.target.value.slice(0, 4000))} maxLength={4000} rows={5} className="mt-1.5 w-full rounded-lg border border-line bg-paper p-3" /></label><label className="text-sm font-medium sm:col-span-2">联系信息（可选）<input value={contact} onChange={(event) => setContact(event.target.value.slice(0, 200))} maxLength={200} className="mt-1.5 h-10 w-full rounded-lg border border-line bg-paper px-2" /></label><div className="sm:col-span-2"><Button type="submit" disabled={busy || !description.trim()}>{busy ? "正在保存…" : "提交至本地收件箱"}</Button>{message ? <p className="mt-3 text-sm text-muted" role="status">{message}</p> : null}</div></form></section></div></main>;
}
