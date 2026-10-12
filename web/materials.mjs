const KEY = "story-archive-materials-v1";
const empty = () => ({ version: 1, snapshot: null, topic: "", passage_ids: [], relationships: [] });
const escape = (value) => String(value ?? "").replace(/[&<>"']/gu, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const validId = (value) => typeof value === "string" && value.length > 0 && value.length <= 160;
const validIds = (value) => Array.isArray(value) && value.length <= 50 && value.every(validId) && new Set(value).size === value.length;

export function readSelection() {
  let raw;
  try { raw = localStorage.getItem(KEY); } catch { throw new Error("浏览器未允许本地存储，素材清单暂不可用；未丢弃已有内容。"); }
  if (raw === null) return empty();
  try {
    if (raw.length > 65536) throw new Error();
    const value = JSON.parse(raw);
    if (!value || value.version !== 1 || (value.snapshot !== null && typeof value.snapshot !== "string") || (value.snapshot !== null && !validId(value.snapshot)) || typeof value.topic !== "string" || value.topic.length > 500 || !validIds(value.passage_ids) || !Array.isArray(value.relationships) || value.relationships.length > 50) throw new Error();
    const ids = new Set();
    for (const relation of value.relationships) {
      if (!relation || !validId(relation.id) || !validIds(relation.evidence_ids) || !relation.evidence_ids.length || ids.has(relation.id)) throw new Error();
      ids.add(relation.id);
    }
    if ((value.passage_ids.length || value.relationships.length) && !value.snapshot) throw new Error();
    return { version: 1, snapshot: value.snapshot, topic: value.topic, passage_ids: value.passage_ids, relationships: value.relationships.map(({ id, evidence_ids }) => ({ id, evidence_ids })) };
  } catch { throw new Error("本地清单格式损坏或版本不支持，尚未覆盖。可以清空后新建清单。"); }
}

function writeSelection(selection) {
  const encoded = JSON.stringify({ version: 1, ...selection });
  if (encoded.length > 65536) throw new Error("清单标识信息超过本地保存上限，请缩小清单；未覆盖原清单。");
  try { localStorage.setItem(KEY, encoded); }
  catch { throw new Error("浏览器无法保存清单，操作未完成；请检查本地存储空间或权限。"); }
}

export async function postJson(path, payload, signal) {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal, cache: "no-store" });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作未完成，请重试。");
  return result;
}

export function createMaterialUI({ context, replacePage, notify, status, setSnapshot }) {
  let busy = false;
  const check = async (selection, addition = null, trackSelection = true) => {
    const initial = context();
    const raw = trackSelection ? JSON.stringify(readSelection()) : null;
    const result = await postJson("/api/materials", {
      snapshot: selection.snapshot, topic: selection.topic, passage_ids: selection.passage_ids, relationships: selection.relationships,
      scope_ids: initial.scopes, purpose: initial.purpose, ...(addition ? { add: addition } : {}),
    }, initial.signal);
    const current = context();
    if (current.version !== initial.version || (trackSelection && JSON.stringify(readSelection()) !== raw)) throw new Error("页面范围或清单已变化，请重新操作。");
    return result;
  };

  async function add(kind, id, button) {
    if (busy) { notify("正在核验上一项素材，请稍后重试。"); return; }
    busy = true; button.disabled = true;
    try {
      const selected = readSelection();
      const snapshot = context().snapshot;
      if (!snapshot) throw new Error("请等待当前档案加载完成。");
      if (selected.snapshot && selected.snapshot !== snapshot) throw new Error("清单已固定到另一个快照。请在素材页返回该快照，或清空后新建；不会混合版本。");
      const result = await check({ ...selected, snapshot }, { kind, id });
      if (!result.valid) throw new Error("素材或清单中的完整证据在当前范围 / 用途下不可用。请到素材页检查并移除失效项。");
      writeSelection(result.selection);
      notify(`已保存素材，独立片段 ${result.count} / 50；重复项不会重复计数。`);
    } catch (error) { if (error.name !== "AbortError") notify(error.message); }
    finally { busy = false; button.disabled = false; }
  }

  async function citation(id, button) {
    button.disabled = true;
    try {
      const result = await check({ ...empty(), snapshot: context().snapshot, passage_ids: [id] }, null, false);
      if (!result.valid) throw new Error("该原文当前不可引用，未复制正文。");
      if (!button.isConnected) throw new Error("页面已经变化，请重新复制。");
      await navigator.clipboard.writeText(result.markdown + `\n档案服务：${location.origin}/\n`);
      notify("引用已复制，包含快照、范围、来源记录和原文定位。");
    } catch (error) { if (error.name !== "AbortError") notify(error.message); }
    finally { button.disabled = false; }
  }

  const clearControls = () => `<details class="clear-materials"><summary>清空并新建清单</summary><p>将移除本浏览器保存的素材 ID 和主题备注。</p><button id="clear-materials" class="button">确认清空本地清单</button></details>`;
  function bindClear() {
    document.querySelector("#clear-materials").addEventListener("click", async () => {
      try { localStorage.removeItem(KEY); await render(); document.querySelector("#material-topic")?.focus(); } catch { notify("浏览器未允许清空本地存储，操作未完成。"); }
    });
  }

  async function render() {
    let selected;
    try { selected = readSelection(); }
    catch (error) {
      replacePage(`<div class="empty-state" role="alert"><h1>素材清单暂不可用</h1><p>${escape(error.message)}</p>${clearControls()}</div>`); bindClear(); return;
    }
    const version = context().version;
    replacePage(`<section class="materials-page"><div class="eyebrow">WORDS TO WORK WITH</div><h1>把证据，整理成素材。</h1>
      <p class="muted">清单保存在此浏览器，清理浏览器数据会丢失。只保存选中 ID 和主题备注；没有云同步。</p>
      <label class="topic-label" for="material-topic">创作主题 / 备注（最多 500 字）</label><textarea id="material-topic" rows="3" maxlength="500" placeholder="例如：围绕师徒关系，整理可追溯证据">${escape(selected.topic)}</textarea>
      <p id="topic-status" role="status" class="small muted"></p>
      <p class="small">固定快照：<code>${escape(selected.snapshot || "加入第一项后固定")}</code></p>
      ${selected.snapshot ? `<a class="text-button" href="#/search?snapshot=${encodeURIComponent(selected.snapshot)}">回到清单快照检索 ↗</a>` : '<a class="text-button" href="#/search">查找素材 →</a>'}
      <div id="material-result" tabindex="-1" aria-live="polite"><p>正在重新核验素材…</p></div>${clearControls()}</section>`);
    bindClear();
    const topic = document.querySelector("#material-topic");
    topic.addEventListener("input", () => {
      try { const current = readSelection(); writeSelection({ ...current, topic: topic.value }); document.querySelector("#topic-status").textContent = "备注已保存到本浏览器。"; }
      catch (error) { document.querySelector("#topic-status").textContent = error.message; }
    });
    const panel = document.querySelector("#material-result");
    let result;
    try {
      const snapshot = selected.snapshot || (await status()).snapshot_id;
      if (version !== context().version || !panel.isConnected) return;
      setSnapshot(snapshot);
      // Topic changes during loading do not discard the draft; rechecking is explicit.
      result = await check({ ...readSelection(), snapshot });
    } catch (error) {
      if (error.name === "AbortError" || version !== context().version || !panel.isConnected) return;
      panel.innerHTML = `<p class="callout" role="alert">${escape(error.message)}</p><button class="button" id="material-retry">重新核验</button>${rows(selected, null)}`;
      bindRows(panel); document.querySelector("#material-retry").addEventListener("click", render); return;
    }
    if (!panel.isConnected) return;
    panel.innerHTML = `<div class="material-summary"><strong>${result.count} / 50 个独立片段</strong><span>${selected.passage_ids.length} 项原文 · ${selected.relationships.length} 项关系</span></div>
      ${result.valid ? '' : '<div class="callout" role="alert">部分素材在当前范围、用途或快照中不可用。未展示受限内容；移除标记项或手动调整范围后重新核验，暂不能导出。</div>'}
      ${rows(selected, result)}
      <div class="material-actions"><button class="button" id="material-retry">重新核验</button>${['copy', 'md', 'json'].map((kind) => `<button class="button button-primary" data-material-export="${kind}" ${result.valid && result.count ? '' : 'disabled'}>${{copy:'复制素材',md:'导出 Markdown',json:'导出 JSON'}[kind]}</button>`).join('')}</div>`;
    bindRows(panel);
    document.querySelector("#material-retry").addEventListener("click", render);
    panel.querySelectorAll("[data-material-export]").forEach((button) => button.addEventListener("click", () => exportSelection(button)));
  }

  function rows(selected, result) {
    const items = [ ...selected.passage_ids.map((id) => ({ kind: 'passage', id })), ...selected.relationships.map((item) => ({ kind: 'relationship', ...item })) ];
    if (!items.length) return '<div class="empty-state"><h2>还没有素材</h2><p>在搜索结果、原文阅读或关系证据面板选择“加入素材”。关系证据也计入片段上限。</p></div>';
    return `<ul class="material-list">${items.map((item) => {
      const record = result?.preview[item.kind === 'passage' ? 'passages' : 'relationships'].find((record) => record.id === item.id);
      const failed = result?.errors.some((error) => error.id === item.id && error.kind === item.kind);
      return `<li><div><span class="tag">${item.kind === 'passage' ? '原文' : '关系与完整证据'}</span> <code>${escape(item.id)}</code>
        <p>${failed ? '当前不可用，请移除或重新调整范围。' : record ? escape(record.text || record.description) : '尚未完成核验，不展示正文。'}</p>
        ${item.evidence_ids ? `<p class="small">固定证据组：${item.evidence_ids.map(escape).join(' + ')}（须联合成立）</p>` : ''}
        ${record && !failed && item.kind === 'passage' ? `<a class="text-button" href="#/read?passage=${encodeURIComponent(item.id)}&snapshot=${encodeURIComponent(selected.snapshot)}">回到原文 ↗</a>` : ''}</div>
        <button class="button" data-remove-kind="${item.kind}" data-remove-id="${escape(item.id)}" aria-label="移除 ${escape(item.id)}">移除</button></li>`;
    }).join('')}</ul>`;
  }

  function bindRows(panel) {
    panel.querySelectorAll("[data-remove-id]").forEach((button) => button.addEventListener("click", async () => {
      try {
        const selected = readSelection();
        if (button.dataset.removeKind === 'passage') selected.passage_ids = selected.passage_ids.filter((id) => id !== button.dataset.removeId);
        else selected.relationships = selected.relationships.filter((relation) => relation.id !== button.dataset.removeId);
        if (!selected.passage_ids.length && !selected.relationships.length) selected.snapshot = null;
        writeSelection(selected); await render(); document.querySelector('#material-result')?.focus({ preventScroll: true }); document.querySelector('#material-result')?.scrollIntoView({ block: 'nearest' });
      } catch (error) { notify(error.message); }
    }));
  }

  async function exportSelection(button) {
    button.disabled = true;
    try {
      const selected = readSelection();
      const result = await check(selected);
      if (!result.valid || !result.count) throw new Error("素材已失效或清单为空。请重新核验并处理标记项，未生成导出。");
      if (!button.isConnected) throw new Error("清单页面已变化，请重新操作。");
      const kind = button.dataset.materialExport;
      if (kind === 'copy') await navigator.clipboard.writeText(result.markdown + `\n档案服务：${location.origin}/\n`);
      else {
        const blob = new Blob([kind === 'json' ? JSON.stringify(result.package, null, 2) : result.markdown], { type: kind === 'json' ? 'application/json' : 'text/markdown;charset=utf-8' });
        const address = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = address; anchor.download = `synthetic-materials.${kind}`; anchor.click(); setTimeout(() => URL.revokeObjectURL(address), 1000);
      }
      notify("素材已重新核验并导出，包含完整证据、快照、范围和来源记录。");
    } catch (error) { if (error.name !== 'AbortError') notify(error.message); }
    finally { button.disabled = false; }
  }

  return { add, citation, render };
}
