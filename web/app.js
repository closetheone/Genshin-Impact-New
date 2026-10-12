import { SCOPES, PREDICATES, normalizeText, searchPassages, orderPassages, characterLabels, neighborhood, scopeLabel, relationScope } from "/model.mjs";

const main = document.querySelector("#main");
const scopeSelect = document.querySelector("#scope-select");
const purposeSelect = document.querySelector("#purpose-select");
const pageNames = { search: "文本检索", read: "原文阅读", graph: "人物关系图" };
const state = { view: null, query: "", center: "person:student", hops: 1, predicate: "all", graphMode: "graph", relation: null };
let requestController;
let requestVersion = 0;
let pageCleanup = () => {};
let toastTimer;

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/gu, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const readLink = (identifier) => snapshotLink(`#/read?passage=${encodeURIComponent(identifier)}`);
const graphLink = (identifier) => snapshotLink(`#/graph?center=${encodeURIComponent(identifier)}`);
const tag = (label, extra = "") => `<span class="tag ${extra}">${escapeHtml(label)}</span>`;

function notify(message) {
  const toast = document.querySelector("#toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
}

function route() {
  const [path, query = ""] = location.hash.slice(1).split("?");
  return { page: path?.replace(/^\//u, "") || "search", params: new URLSearchParams(query) };
}

function snapshotLink(address) {
  if (!state.view) return address;
  const [path, query = ""] = address.split("?");
  const parameters = new URLSearchParams(query);
  parameters.set("snapshot", state.view.snapshot_id);
  return `${path}?${parameters}`;
}

function replacePage(markup) {
  pageCleanup();
  pageCleanup = () => {};
  main.innerHTML = markup;
  main.querySelectorAll('a[href^="#/"]').forEach((anchor) => { anchor.href = snapshotLink(anchor.getAttribute("href")); });
}

async function fetchView(purpose, signal, snapshot = route().params.get("snapshot")) {
  const query = new URLSearchParams({ purpose });
  if (snapshot !== null) query.set("snapshot", snapshot);
  SCOPES[scopeSelect.value].forEach((scope) => query.append("scope", scope));
  const response = await fetch(`/api/view?${query}`, { signal, cache: "no-store" });
  if (response.status === 404) throw new Error("指定快照不可用，未替换成其他版本。可手动读取当前发布快照。");
  if (!response.ok) throw new Error("读取失败，请确认本地服务、数据库与导入状态后重试。");
  const view = await response.json();
  if (view.dataset_kind !== "synthetic") throw new Error("此原型只接受明确标注的原创合成样本。");
  return view;
}

async function loadView() {
  requestController?.abort();
  requestController = new AbortController();
  const version = ++requestVersion;
  state.view = null;
  document.querySelector("#archive-snapshot").textContent = "正在读取本地 SQLite 档案…";
  document.querySelector("#toast").hidden = true;
  replacePage('<div class="loading-state" role="status">正在按当前范围与用途打开档案…</div>');
  try {
    const view = await fetchView(purposeSelect.value, requestController.signal);
    if (version !== requestVersion) return;
    state.view = view;
    history.replaceState(null, "", snapshotLink(location.hash || "#/search"));
    document.querySelector("#archive-snapshot").textContent = `SQLite 本地存储 · 已固定快照 ${view.snapshot_id}`;
    document.querySelectorAll(".primary-nav a, .brand").forEach((anchor) => { anchor.href = snapshotLink(anchor.getAttribute("href")); });
    render();
  } catch (error) {
    if (error.name === "AbortError" || version !== requestVersion) return;
    document.querySelector("#archive-snapshot").textContent = "档案未加载；没有回退到其他数据源。";
    replacePage(`<div class="empty-state" role="alert"><h2>档案暂未打开</h2><p>${escapeHtml(error.message)}</p><button id="retry" class="button">重新读取</button></div>`);
    document.querySelector("#retry").addEventListener("click", loadView);
  }
}

function render() {
  const current = route();
  document.querySelector("#page-name").textContent = pageNames[current.page] || "未找到页面";
  document.title = `${pageNames[current.page] || "未找到页面"} · 原神文本档案 · 原创样本`;
  document.querySelectorAll("[data-page]").forEach((anchor) => {
    if (anchor.dataset.page === current.page) anchor.setAttribute("aria-current", "page");
    else anchor.removeAttribute("aria-current");
  });
  if (!state.view) return;
  try {
    if (current.page === "search") renderSearch();
    else if (current.page === "read") renderReader(current.params.get("passage"));
    else if (current.page === "graph") renderGraph(current.params.get("center"));
    else replacePage('<div class="empty-state"><h2>未找到这个页面</h2><a class="button" href="#/search">返回文本检索</a></div>');
  } catch (error) {
    replacePage(`<div class="empty-state" role="alert"><h2>无法展示当前样本</h2><p>${escapeHtml(error.message)}</p><a class="button" href="#/search">返回文本检索</a></div>`);
  }
}

function highlighted(text, query) {
  if (!query || !text.includes(query)) return escapeHtml(text);
  return text.split(query).map(escapeHtml).join(`<mark>${escapeHtml(query)}</mark>`);
}

function renderSearch() {
  const view = state.view;
  const labels = characterLabels(view.characters);
  const results = searchPassages(orderPassages(view.passages), state.query);
  const query = normalizeText(state.query);
  replacePage(`
    <section class="hero"><div class="eyebrow">READ THE WORDS. TRACE THE STORY.</div>
      <h1>从一句话，找到故事的来处。</h1><p>检索文本，回到上下文，再沿着证据探索人物之间的关系。</p>
      <div class="hero-art" aria-hidden="true"><span>✦</span></div>
    </section>
    <form class="search-form" role="search"><span class="search-symbol" aria-hidden="true">⌕</span>
      <input id="search-input" aria-label="搜索原创样本文本" maxlength="200" placeholder="输入关键词或一句对白…" value="${escapeHtml(state.query)}">
      <button class="button button-primary" type="submit">检索文本 <span aria-hidden="true">→</span></button>
    </form>
    <div class="suggestions"><span>试着搜索</span>${["师父", "修桥", "先核对物资"].map((queryText) => `<button data-query="${queryText}">${queryText}</button>`).join("")}<span>仅搜索当前范围内的原创样本</span></div>
    <div class="stats-row" aria-label="当前范围统计">
      <div class="stat"><strong>${view.passages.length}</strong><span>文本段落</span></div>
      <div class="stat"><strong>${view.characters.length}</strong><span>样本人物</span></div>
      <div class="stat"><strong>${view.relationships.length}</strong><span>有据关系</span></div>
      <div class="stat-label"><span class="status-dot"></span>当前范围 · 当前用途</div>
    </div>
    <div class="content-grid"><section aria-label="检索结果"><div class="section-heading"><h2>${query ? "检索结果" : "浏览文本"}</h2><span class="muted" role="status">${results.length} 个独立出现位置</span></div>
      <div class="result-list">${results.length ? results.map((passage, index) => `
        <article class="result"><span class="result-number">${String(index + 1).padStart(2, "0")}</span><div class="result-body">
          <div class="result-meta">${tag(scopeLabel(passage))}<span class="result-title">${escapeHtml(view.entries.find((entry) => entry.id === passage.entry_id)?.title)}</span></div>
          <a class="result-text" href="${readLink(passage.id)}">${highlighted(passage.text, query)}</a>
          <div class="result-bottom"><span>${escapeHtml(labels.get(passage.speaker_id) || "叙述")} · <code>${escapeHtml(passage.id)}</code></span><a class="text-button" href="${readLink(passage.id)}">回到原文 ↗</a></div>
        </div></article>`).join("") : '<div class="empty-state"><div class="empty-symbol">⌕</div><h2>没有找到这句话</h2><p>试试更短的关键词，或手动调整内容范围。不会自动打开后续内容。</p></div>'}</div>
    </section><aside class="search-aside"><div class="aside-card"><div class="eyebrow">FEATURED SAMPLE</div><div class="archive-stamp" aria-hidden="true">卷</div><h3>修桥小队</h3><p>一段原创小故事，串起人物、分支对白与完整证据。用它验证阅读与取材的每一步。</p>${tag("非原神剧情", "tag-warm")}<a class="button button-soft" href="#/read">打开样本卷宗 ↗</a></div>
      <div class="aside-info"><h3>文字之外，也有线索</h3><p>师徒、亲属、合作与对立。每条展示的关系，都能找到支持它的原文。</p><a class="text-button" href="#/graph">探索人物关系图 →</a><div class="inline-divider"></div><p>当前为字面匹配原型，不支持语义检索。相同对白的不同出处分别保留。</p><code>${escapeHtml(view.snapshot_id)}</code></div>
    </aside></div>`);
  document.querySelector(".search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.query = document.querySelector("#search-input").value;
    renderSearch();
    document.querySelector("#search-input").focus();
  });
  document.querySelector("#search-input").addEventListener("input", (event) => { state.query = event.target.value; });
  document.querySelectorAll("[data-query]").forEach((button) => button.addEventListener("click", () => {
    state.query = button.dataset.query;
    renderSearch();
  }));
}

function renderReader(targetId) {
  const view = state.view;
  const labels = characterLabels(view.characters);
  const passages = orderPassages(view.passages);
  const unavailable = targetId && !passages.some((passage) => passage.id === targetId);
  let previousSection;
  replacePage(`
    <div class="page-title-row"><div><div class="eyebrow">THE READING ROOM</div><h1>让解读，回到原文。</h1></div><a class="button" href="#/graph">探索人物关系 ↗</a></div>
    ${unavailable ? '<div class="callout" role="alert">这个位置在当前范围、用途或快照中不可用。未自动扩大范围，也未加载隐藏正文。</div>' : ""}
    <div class="reader-layout"><article class="reading-paper"><header class="document-header"><div class="eyebrow">ORIGINAL SYNTHETIC FIXTURE / 001</div><h2>${escapeHtml(view.entries[0]?.title || "暂无可用条目")}</h2><div class="document-meta">${tag("原创测试 · 非原神剧情", "tag-warm")}<span>${passages.length} 段可读文本</span><span>按显式对话连接排序</span></div></header>
      <div class="callout">只展示当前边界内的段落，缺失处不补写。两条分支分开展示，不代表同时发生；切换范围可单独阅读。</div>
      ${passages.map((passage) => {
        const section = scopeLabel(passage);
        const header = section !== previousSection ? `<h3 class="branch-heading">${escapeHtml(section)}</h3>` : "";
        previousSection = section;
        return `${header}<section class="passage ${passage.speaker_id ? "" : "narration"} ${passage.id === targetId ? "selected" : ""}" id="${escapeHtml(passage.id)}" tabindex="-1">
          <span class="passage-number">${escapeHtml(passage.id.split(":").at(-1))}</span><div class="passage-speaker">${escapeHtml(labels.get(passage.speaker_id) || "叙述")}${passage.id === targetId ? tag("定位段落", "tag-warm") : ""}</div>
          <p>${escapeHtml(passage.text)}</p><div class="passage-actions"><code>${escapeHtml(passage.id)}</code><button class="text-button" data-copy="${escapeHtml(passage.id)}">复制引用 ↗</button></div>
          <details class="passage-source"><summary>出处与对话连接</summary><code>${escapeHtml(passage.source_id)}<br>${escapeHtml(passage.source_locator)}</code><div>当前可见后续：${passage.next_ids.map((identifier) => `<a class="text-button" href="${readLink(identifier)}">${escapeHtml(identifier)}</a>`).join(" · ") || "无（不表示完整剧情结束）"}</div></details>
        </section>`;
      }).join("")}
    </article><aside class="reader-aside"><div class="aside-card"><div class="eyebrow">READ WITH CONTEXT</div><h3>一段话，不止一句。</h3><p>人物身份、发生分支和后续证据，都是理解一句对白的上下文。</p><div class="outline-list">${passages.filter((passage, index) => !index || scopeLabel(passage) !== scopeLabel(passages[index - 1])).map((passage) => `<button data-scroll="${escapeHtml(passage.id)}">${escapeHtml(scopeLabel(passage))} · ${escapeHtml(passage.id)}</button>`).join("")}</div></div><div class="aside-info"><h3>引用与使用边界</h3><p>复制前会重新核验导出用途。可读不等于可导出；快照变化时请先刷新。</p><code>${escapeHtml(view.snapshot_id)}</code></div></aside></div>`);
  document.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", () => copyCitation(button)));
  document.querySelectorAll("[data-scroll]").forEach((button) => button.addEventListener("click", () => focusPassage(button.dataset.scroll)));
  if (targetId && !unavailable) requestAnimationFrame(() => focusPassage(targetId));
}

function focusPassage(identifier) {
  const element = document.getElementById(identifier);
  if (route().page !== "read" || !element) return;
  element.scrollIntoView({ block: "center" });
  element.focus({ preventScroll: true });
}

async function checkedExportView() {
  const original = state.view;
  const version = requestVersion;
  const view = await fetchView("export", requestController.signal, original.snapshot_id);
  if (version !== requestVersion || original !== state.view || view.snapshot_id !== original.snapshot_id) {
    throw new Error("范围或快照已经变化，请刷新后重新操作。");
  }
  return view;
}

async function copyCitation(button) {
  button.disabled = true;
  try {
    const view = await checkedExportView();
    const passage = view.passages.find((candidate) => candidate.id === button.dataset.copy);
    if (!passage) throw new Error("此段落当前不可导出，未复制正文。");
    const speaker = characterLabels(view.characters).get(passage.speaker_id) || "叙述";
    const permalink = new URL(readLink(passage.id), location.href).href;
    await navigator.clipboard.writeText(`[原创合成样本，非原神剧情]\n${speaker}：${passage.text}\n${passage.id} · ${view.snapshot_id}\n${passage.source_id} · ${passage.source_locator}\n范围：${view.scope_ids.join(", ")}\n本机定位链接（不自动扩大范围）：${permalink}`);
    notify("引用已复制，包含原创样本标识、快照和出处。");
  } catch (error) {
    if (error.name !== "AbortError") notify(error.name === "NotAllowedError" ? "浏览器未允许剪贴板操作，未复制内容。" : error.message);
  } finally {
    button.disabled = false;
  }
}

function renderGraph(requestedCenter) {
  const view = state.view;
  if (requestedCenter) state.center = requestedCenter;
  const labels = characterLabels(view.characters);
  const unavailable = !labels.has(state.center);
  const graph = neighborhood(view, state.center, state.hops, state.predicate);
  if (!graph.edges.some((relation) => relation.id === state.relation)) state.relation = graph.edges[0]?.id || null;
  replacePage(`
    <div class="page-title-row"><div><div class="eyebrow">PEOPLE, CONNECTED BY WORDS</div><h1>关系有据，故事有迹。</h1></div><button class="button" id="export-graph" ${graph.nodes.length ? "" : "disabled"}>导出关系 JSON ↗</button></div>
    <div class="graph-toolbar"><label><span>中心人物</span><select id="graph-center" aria-label="中心人物">${unavailable ? '<option value="" selected>当前人物不可用</option>' : ""}${view.characters.map((character) => `<option value="${escapeHtml(character.id)}" ${character.id === state.center ? "selected" : ""}>${escapeHtml(labels.get(character.id))}</option>`).join("")}</select></label>
      <label><span>展开层级</span><select id="graph-hops" aria-label="展开层级"><option value="1" ${state.hops === 1 ? "selected" : ""}>一跳关系</option><option value="2" ${state.hops === 2 ? "selected" : ""}>二跳关系</option></select></label>
      <label><span>关系类型</span><select id="graph-predicate" aria-label="关系类型"><option value="all">全部类型</option>${Object.entries(PREDICATES).map(([key, value]) => `<option value="${key}" ${state.predicate === key ? "selected" : ""}>${value.label}</option>`).join("")}</select></label>
      <span class="toolbar-spacer"></span><div class="segmented" aria-label="图谱展示方式"><button data-mode="graph" aria-pressed="${state.graphMode === "graph"}">图谱</button><button data-mode="list" aria-pressed="${state.graphMode === "list"}">列表</button></div>
    </div>
    ${unavailable ? '<div class="callout" role="alert">当前人物在此范围、用途或快照中不可用。请选择一个可见人物，不会自动扩大范围。</div>' : ""}
    ${graph.truncated ? '<div class="callout">局部图已截断至 50 个人物 / 100 条关系。原型尚不支持续取，请缩小范围。</div>' : ""}
    <div class="graph-layout"><section class="graph-stage" aria-label="人物关系"><div class="graph-topline"><strong>${graph.nodes.length} 个人物 · ${graph.edges.length} 条关系</strong><span>已审核 · 明确断言 · 完整证据</span></div>
      ${state.graphMode === "graph" ? '<div class="graph-canvas"><svg id="relationship-svg" role="group" aria-label="局部人物关系图，Tab 可选择人物或关系"></svg><span class="graph-watermark">SYNTHETIC STORY / NOT GAME LORE</span><div class="graph-controls"><button data-zoom="out" aria-label="缩小图谱">−</button><span id="zoom-level">100%</span><button data-zoom="in" aria-label="放大图谱">+</button><button data-zoom="reset" aria-label="重置布局">↺</button></div></div>' : `<div class="relationship-list">${graph.edges.length ? graph.edges.map((relation) => `<button class="relationship-row" data-relation="${escapeHtml(relation.id)}" aria-pressed="${relation.id === state.relation}"><strong>${escapeHtml(labels.get(relation.from_id))} ${relation.direction === "directed" ? "→" : "—"} ${escapeHtml(labels.get(relation.to_id))}</strong><span>${PREDICATES[relation.predicate].label} · ${escapeHtml(relationScope(relation, view.passages))}</span></button>`).join("") : '<div class="empty-state">当前条件下没有可用关系。可切换中心人物或筛选条件。</div>'}</div>`}
      <div class="graph-legend">${Object.values(PREDICATES).map((predicate) => `<span><i class="legend-line" style="--relation-color:${predicate.color}"></i>${predicate.label}</span>`).join("")}<span>→ 有向关系　— 对称关系</span></div>
    </section><aside class="evidence-panel" id="evidence-panel" aria-label="关系证据" aria-live="polite"></aside></div>
    <div class="graph-footnote"><p>点击连线查看原文证据；拖动人物调整位置，拖动画布平移，使用 + / − 缩放。键盘可选择连线；人物按 Enter 设为中心。</p><p>分支与后续证据分别标注，不把共现当作关系，也不把不同分支当作同一时刻。这里只演示原创样本。</p></div>`);
  document.querySelector("#graph-center").addEventListener("change", (event) => { location.hash = graphLink(event.target.value); });
  document.querySelector("#graph-hops").addEventListener("change", (event) => { state.hops = Number(event.target.value); renderGraph(); });
  document.querySelector("#graph-predicate").addEventListener("change", (event) => { state.predicate = event.target.value; renderGraph(); });
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => { state.graphMode = button.dataset.mode; renderGraph(); }));
  document.querySelectorAll("[data-relation]").forEach((button) => button.addEventListener("click", () => selectRelation(button.dataset.relation)));
  document.querySelector("#export-graph").addEventListener("click", (event) => exportGraph(event.currentTarget, graph));
  renderEvidence(graph.edges.find((relation) => relation.id === state.relation));
  if (state.graphMode === "graph") mountGraph(graph, labels);
}

function selectRelation(identifier) {
  state.relation = identifier;
  document.querySelectorAll(".graph-edge").forEach((element) => {
    element.classList.toggle("selected", element.dataset.relation === identifier);
    element.setAttribute("aria-pressed", String(element.dataset.relation === identifier));
  });
  document.querySelectorAll(".relationship-row").forEach((element) => element.setAttribute("aria-pressed", String(element.dataset.relation === identifier)));
  renderEvidence(state.view.relationships.find((relation) => relation.id === identifier));
}

function renderEvidence(relation) {
  const panel = document.querySelector("#evidence-panel");
  if (!relation) {
    panel.innerHTML = '<div class="eyebrow">FOLLOW THE EVIDENCE</div><h2>等待一条有据的连线</h2><p class="small muted">当前局部图没有可用关系。不会用人物共现或 AI 猜测补齐。</p>';
    return;
  }
  const view = state.view;
  const labels = characterLabels(view.characters);
  const person = (identifier) => `<span>${escapeHtml(view.characters.find((character) => character.id === identifier)?.name)}<small>${escapeHtml(identifier)}</small></span>`;
  panel.innerHTML = `<div class="eyebrow">FOLLOW THE EVIDENCE</div><h2>关系与原文证据</h2><div class="relation-people">${person(relation.from_id)}<span class="relation-arrow">${relation.direction === "directed" ? "→" : "—"}</span>${person(relation.to_id)}</div>
    ${tag(PREDICATES[relation.predicate].label)} ${tag("已审核 · 明确断言", "tag-blue")}<p class="relation-description">${escapeHtml(relation.description)}</p><p class="small muted">${escapeHtml(relationScope(relation, view.passages))}</p>
    ${relation.evidence_groups.map((group, index) => `<div class="evidence-group-label">证据组 ${index + 1} · ${group.length > 1 ? `${group.length} 段须联合阅读` : "单段支持"}</div>${group.map((identifier) => {
      const passage = view.passages.find((candidate) => candidate.id === identifier);
      return `<blockquote class="evidence-quote"><p>${escapeHtml(passage.text)}</p><footer>${escapeHtml(labels.get(passage.speaker_id) || "叙述")} · ${escapeHtml(scopeLabel(passage))}<a class="text-button" href="${readLink(identifier)}">${escapeHtml(identifier)} · 回到原文 ↗</a></footer></blockquote>`;
    }).join("")}`).join("")}
    <div class="evidence-note">组内段落须共同成立；不同完整证据组可独立支持同一断言。样本断言不等于原神设定。</div><div class="evidence-footer"><code>${escapeHtml(relation.id)}<br>${escapeHtml(view.snapshot_id)}</code></div>`;
}

async function exportGraph(button, graph) {
  const selection = { center_id: state.center, hops: state.hops, predicate: state.predicate };
  button.disabled = true;
  try {
    const view = await checkedExportView();
    if (!button.isConnected) throw new Error("图谱选择已经变化，请重新导出。");
    const permitted = new Map(view.relationships.map((relation) => [relation.id, relation]));
    if (graph.nodes.some((node) => !view.characters.some((character) => character.id === node.id)) || graph.edges.some((edge) => !permitted.has(edge.id))) {
      throw new Error("当前图含不可导出内容，请切换到「素材导出」用途后重试。");
    }
    const relationships = graph.edges.map((edge) => permitted.get(edge.id));
    const evidenceIds = new Set(relationships.flatMap((relation) => relation.evidence_groups.flat()));
    const output = {
      dataset_kind: view.dataset_kind, notice: view.notice, snapshot_id: view.snapshot_id,
      scope_ids: view.scope_ids, purpose: "export", ...selection, truncated: graph.truncated,
      characters: view.characters.filter((character) => graph.nodes.some((node) => node.id === character.id)),
      relationships, evidence: view.passages.filter((passage) => evidenceIds.has(passage.id)),
    };
    const address = URL.createObjectURL(new Blob([JSON.stringify(output, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = address;
    anchor.download = "synthetic-character-graph.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(address), 1000);
    notify("已导出当前局部关系和完整证据，保留原创样本标识。");
  } catch (error) {
    if (error.name !== "AbortError") notify(error.message);
  } finally {
    button.disabled = false;
  }
}

function mountGraph(graph, labels) {
  const svg = document.querySelector("#relationship-svg");
  const container = svg.parentElement;
  const positions = new Map();
  let width;
  let height;
  let scale = 1;
  let pan = { x: 0, y: 0 };
  let gesture;
  let moved = false;

  function reset() {
    width = container.clientWidth;
    height = container.clientHeight;
    scale = 1;
    pan = { x: 0, y: 0 };
    graph.nodes.forEach((node, index) => {
      const angle = (index - 1) * Math.PI * 2 / Math.max(1, graph.nodes.length - 1) - Math.PI / 2;
      const compactLayouts = {
        2: [[.25, .43], [.75, .43]],
        3: [[.24, .45], [.74, .2], [.74, .7]],
        4: [[.2, .2], [.8, .2], [.8, .66], [.2, .66]],
      };
      const compact = compactLayouts[graph.nodes.length]?.[index];
      positions.set(node.id, compact ? { x: width * compact[0], y: height * compact[1] } : index === 0 ? { x: width / 2, y: height / 2 } : {
        x: width / 2 + Math.cos(angle) * Math.max(50, width / 2 - 77),
        y: height / 2 + Math.sin(angle) * (height / 2 - 83),
      });
    });
    draw();
  }

  function draw() {
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = `<defs>${Object.entries(PREDICATES).map(([key, predicate]) => `<marker id="arrow-${key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${predicate.color}"/></marker>`).join("")}</defs><g id="graph-world"></g>`;
    const world = svg.querySelector("#graph-world");
    world.setAttribute("transform", `translate(${pan.x} ${pan.y}) scale(${scale})`);
    world.innerHTML = graph.edges.map((relation) => {
      const start = positions.get(relation.from_id);
      const end = positions.get(relation.to_id);
      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const length = Math.max(1, Math.hypot(dx, dy));
      const peers = graph.edges.filter((candidate) => [candidate.from_id, candidate.to_id].sort().join("|") === [relation.from_id, relation.to_id].sort().join("|"));
      const offset = (peers.indexOf(relation) - (peers.length - 1) / 2) * 112;
      const canonicalDirection = relation.from_id < relation.to_id ? 1 : -1;
      const control = { x: (start.x + end.x) / 2 - dy / length * offset * canonicalDirection, y: (start.y + end.y) / 2 + dx / length * offset * canonicalDirection };
      const fromLength = Math.max(1, Math.hypot(control.x - start.x, control.y - start.y));
      const toLength = Math.max(1, Math.hypot(end.x - control.x, end.y - control.y));
      const from = { x: start.x + (control.x - start.x) / fromLength * 32, y: start.y + (control.y - start.y) / fromLength * 32 };
      const to = { x: end.x - (end.x - control.x) / toLength * 34, y: end.y - (end.y - control.y) / toLength * 34 };
      const path = `M ${from.x} ${from.y} Q ${control.x} ${control.y} ${to.x} ${to.y}`;
      const middle = { x: (from.x + 2 * control.x + to.x) / 4, y: (from.y + 2 * control.y + to.y) / 4 };
      const predicate = PREDICATES[relation.predicate];
      const condition = relation.branch_id === "east" ? " · 东" : relation.branch_id === "west" ? " · 西" : "";
      const labelWidth = condition ? 54 : 36;
      const labelX = Math.min(width - labelWidth / 2 - 8, Math.max(labelWidth / 2 + 8, middle.x));
      return `<g class="graph-edge ${relation.id === state.relation ? "selected" : ""}" data-relation="${escapeHtml(relation.id)}" tabindex="0" role="button" aria-pressed="${relation.id === state.relation}" aria-label="${escapeHtml(`${labels.get(relation.from_id)} ${relation.direction === "directed" ? "指向" : "与"} ${labels.get(relation.to_id)}，${predicate.label}，${relationScope(relation, state.view.passages)}，查看证据`)}"><path class="edge-hit" d="${path}"/><path class="edge-path" d="${path}" stroke="${predicate.color}" ${relation.direction === "directed" ? `marker-end="url(#arrow-${relation.predicate})"` : ""}/><rect class="edge-label-bg" x="${labelX - labelWidth / 2}" y="${middle.y - 10}" width="${labelWidth}" height="20"/><text class="edge-label" x="${labelX}" y="${middle.y}" fill="${predicate.color}">${predicate.label}${condition}</text></g>`;
    }).join("") + graph.nodes.map((node) => {
      const position = positions.get(node.id);
      const duplicated = labels.get(node.id) !== node.name;
      const stableNumber = state.view.characters.findIndex((character) => character.id === node.id) + 1;
      return `<g class="graph-node ${node.id === state.center ? "center" : ""}" data-node="${escapeHtml(node.id)}" transform="translate(${position.x} ${position.y})" tabindex="0" role="button" aria-label="${escapeHtml(labels.get(node.id))}，设为中心"><title>${escapeHtml(labels.get(node.id))}</title><circle class="node-halo" r="33"/><circle class="node-disc" r="26"/><text class="node-monogram" y="1">${escapeHtml(node.name.slice(0, 1))}</text><text class="node-label" y="51">${escapeHtml(node.name)}${duplicated ? ` · ${String(stableNumber).padStart(2, "0")}` : ""}</text><text class="node-subtitle" y="65">${node.id === state.center ? "中心人物" : "原创样本人物"}</text></g>`;
    }).join("");
    document.querySelector("#zoom-level").textContent = `${Math.round(scale * 100)}%`;
  }

  function activate(event) {
    const edge = event.target.closest("[data-relation]");
    const node = event.target.closest("[data-node]");
    if (edge) selectRelation(edge.dataset.relation);
    if (node) location.hash = graphLink(node.dataset.node);
  }

  svg.addEventListener("click", (event) => { if (!moved) activate(event); });
  svg.addEventListener("keydown", (event) => {
    if (["Enter", " "].includes(event.key)) { event.preventDefault(); activate(event); }
  });
  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("[data-relation]")) return;
    moved = false;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const node = event.target.closest("[data-node]");
    gesture = { pointer: event.pointerId, point, nodeId: node?.dataset.node, pan: { ...pan }, position: node ? { ...positions.get(node.dataset.node) } : null };
  });
  svg.addEventListener("pointermove", (event) => {
    if (!gesture || event.pointerId !== gesture.pointer) return;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const delta = { x: point.x - gesture.point.x, y: point.y - gesture.point.y };
    if (!moved && Math.hypot(delta.x, delta.y) < 4) return;
    moved = true;
    svg.setPointerCapture(event.pointerId);
    if (gesture.nodeId) positions.set(gesture.nodeId, {
      x: Math.min(width - 40, Math.max(40, gesture.position.x + delta.x / scale)),
      y: Math.min(height - 80, Math.max(40, gesture.position.y + delta.y / scale)),
    });
    else pan = { x: gesture.pan.x + delta.x, y: gesture.pan.y + delta.y };
    draw();
  });
  const finish = () => { gesture = null; setTimeout(() => { moved = false; }, 0); };
  svg.addEventListener("pointerup", finish);
  svg.addEventListener("pointercancel", finish);
  svg.addEventListener("lostpointercapture", finish);
  svg.addEventListener("pointerleave", () => { if (!moved) gesture = null; });
  document.querySelectorAll("[data-zoom]").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.zoom === "reset") { reset(); return; }
    const nextScale = Math.max(.6, Math.min(1.8, scale + (button.dataset.zoom === "in" ? .2 : -.2)));
    pan = { x: width / 2 - (width / 2 - pan.x) * nextScale / scale, y: height / 2 - (height / 2 - pan.y) * nextScale / scale };
    scale = nextScale;
    draw();
  }));
  const observer = new ResizeObserver(reset);
  observer.observe(container);
  pageCleanup = () => observer.disconnect();
  reset();
}

scopeSelect.addEventListener("change", loadView);
purposeSelect.addEventListener("change", loadView);
window.addEventListener("hashchange", () => {
  if (!state.view || route().params.get("snapshot") !== state.view.snapshot_id) loadView();
  else render();
  window.scrollTo(0, 0);
});
document.querySelector("#open-active").addEventListener("click", () => {
  history.replaceState(null, "", "#/search");
  loadView();
});
document.querySelector(".skip-link").addEventListener("click", (event) => { event.preventDefault(); main.focus(); });
loadView();
