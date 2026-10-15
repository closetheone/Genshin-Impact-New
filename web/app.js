import { createMaterialUI, postJson } from "/materials.mjs";
import { SCOPES, PREDICATES, orderPassages, characterLabels, safeLayout, scopeLabel, relationScope } from "/model.mjs";

const main = document.querySelector("#main");
const scopeSelect = document.querySelector("#scope-select");
const purposeSelect = document.querySelector("#purpose-select");
const pageNames = { search: "文本检索", read: "原文阅读", graph: "人物关系图", characters: "角色目录", character: "角色详情", materials: "素材清单", about: "收录与纠错" };
const state = { view: null, query: "", searchQuery: "", searchMode: "literal", category: "all", speaker: "all", pageSize: 8, characterQuery: "", characterFilter: "all", center: "person:student", hops: 1, predicate: "all", condition: "all", graphPage: 1, graphMode: "graph", relation: null };
let requestController;
let requestVersion = 0;
let pageCleanup = () => {};
let toastTimer;
let evidenceVersion = 0;
let graphLayout = null;
let captureLayout = () => null;
let feedbackAttempt = null;
let feedbackDraft = { request_id: crypto.randomUUID(), kind: "text", snapshot: "", reference: "", description: "", contact: "" };
const materialUI = createMaterialUI({
  context: () => ({ snapshot: state.view?.snapshot_id, scopes: SCOPES[scopeSelect.value], purpose: purposeSelect.value, version: requestVersion, signal: requestController?.signal }),
  replacePage, notify,
  status: () => fetchArchive("/api/status", purposeSelect.value, requestController.signal, route().params.get("snapshot")),
  setSnapshot: (snapshot) => {
    state.view = { snapshot_id: snapshot };
    history.replaceState(null, "", snapshotLink(location.hash));
    document.querySelectorAll(".primary-nav a, .brand").forEach((anchor) => { anchor.href = snapshotLink(anchor.getAttribute("href")); });
    document.querySelector("#archive-snapshot").textContent = `素材核验快照 · ${snapshot}`;
  },
});

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/gu, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const readLink = (identifier) => snapshotLink(`#/read?passage=${encodeURIComponent(identifier)}`);
const characterDetailLink = (identifier) => snapshotLink(`#/character?id=${encodeURIComponent(identifier)}`);
const graphLink = (identifier) => snapshotLink(`#/graph?center=${encodeURIComponent(identifier)}&hops=${state.hops}&predicate=${encodeURIComponent(state.predicate)}&condition=${encodeURIComponent(state.condition)}`);
const graphRelationLink = (identifier, relation) => snapshotLink(`#/graph?center=${encodeURIComponent(identifier)}&hops=${state.hops}&predicate=${encodeURIComponent(state.predicate)}&condition=${encodeURIComponent(state.condition)}&relation=${encodeURIComponent(relation)}`);
const tag = (label, extra = "") => `<span class="tag ${extra}">${escapeHtml(label)}</span>`;
const validPurposes = new Set(["display", "export", "external_ai"]);

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
  parameters.set("scope", scopeSelect.value);
  parameters.set("purpose", purposeSelect.value);
  return `${path}?${parameters}`;
}

function restoreBoundary() {
  const params = route().params;
  if (Object.hasOwn(SCOPES, params.get("scope"))) scopeSelect.value = params.get("scope");
  if (validPurposes.has(params.get("purpose"))) purposeSelect.value = params.get("purpose");
}

function replacePage(markup) {
  pageCleanup();
  pageCleanup = () => {};
  main.innerHTML = markup;
  main.querySelectorAll("[data-add-passage], [data-add-relation]").forEach((button) => button.addEventListener("click", () => materialUI.add(button.dataset.addPassage ? "passage" : "relationship", button.dataset.addPassage || button.dataset.addRelation, button)));
  main.querySelectorAll('a[href^="#/"]').forEach((anchor) => { anchor.href = snapshotLink(anchor.getAttribute("href")); });
}

async function fetchArchive(path, purpose, signal, snapshot, extra = {}) {
  const query = new URLSearchParams({ purpose, ...extra });
  if (snapshot !== null) query.set("snapshot", snapshot);
  SCOPES[scopeSelect.value].forEach((scope) => query.append("scope", scope));
  const response = await fetch(`${path}?${query}`, { signal, cache: "no-store" });
  if (response.status === 404 || response.status === 409) {
    const failure = await response.json();
    throw new Error(failure.error);
  }
  if (response.status === 400 && extra.cursor) throw new Error("分页与当前查询不匹配，或服务已重启。请从第一页重新检索。");
  if (!response.ok) throw new Error("读取失败，请确认本地服务、数据库与导入状态后重试。");
  const view = await response.json();
  if (view.dataset_kind !== "synthetic") throw new Error("此原型只接受明确标注的原创合成样本。");
  return view;
}

function fetchReader(purpose, signal, snapshot = route().params.get("snapshot"), cursor = null) {
  return fetchArchive("/api/read", purpose, signal, snapshot, { ...(route().params.get("passage") ? { id: route().params.get("passage") } : {}), ...(cursor ? { cursor } : {}) });
}

function fetchGraph(purpose, signal, snapshot = route().params.get("snapshot"), cursor = null) {
  return fetchArchive("/api/graph", purpose, signal, snapshot, { center: state.center, hops: String(state.hops), predicate: state.predicate, condition: state.condition, page: String(state.graphPage), ...(cursor ? { cursor } : {}) });
}

async function loadView(cursor = null) {
  requestController?.abort();
  evidenceVersion += 1;
  restoreBoundary();
  if (route().page === "graph") restoreGraphQuery();
  requestController = new AbortController();
  const version = ++requestVersion;
  state.view = null;
  document.querySelector("#archive-snapshot").textContent = "正在读取本地 SQLite 档案…";
  document.querySelector("#toast").hidden = true;
  replacePage('<div class="loading-state" role="status">正在按当前范围与用途打开档案…</div>');
  try {
    updateNavigation();
    if (route().page === "materials") { await materialUI.render(); return; }
    if (route().page === "about") { await renderAbout(); return; }
    if (route().page === "character") {
      const id = route().params.get("id") || "";
      const view = await fetchArchive("/api/character", purposeSelect.value, requestController.signal, route().params.get("snapshot"), { id });
      if (version !== requestVersion) return;
      state.view = view;
      history.replaceState(null, "", snapshotLink(location.hash));
      document.querySelector("#archive-snapshot").textContent = `SQLite 本地存储 · 已固定快照 ${view.snapshot_id}`;
      document.querySelectorAll(".primary-nav a, .brand").forEach((anchor) => { anchor.href = snapshotLink(anchor.getAttribute("href")); });
      render();
      return;
    }
    const isSearch = route().page === "search";
    const parameters = { q: state.searchQuery, mode: state.searchMode, category: state.category, speaker: state.speaker, limit: String(state.pageSize) };
    if (cursor) parameters.cursor = cursor;
    const isGraph = route().page === "graph";
    const isCharacters = route().page === "characters";
    const view = isSearch
      ? await fetchArchive("/api/search", purposeSelect.value, requestController.signal, route().params.get("snapshot"), parameters)
      : isGraph
        ? await fetchGraph(purposeSelect.value, requestController.signal, route().params.get("snapshot"), cursor)
        : isCharacters
          ? await fetchArchive("/api/characters", purposeSelect.value, requestController.signal, route().params.get("snapshot"), { q: "", limit: "200" })
          : await fetchReader(purposeSelect.value, requestController.signal, route().params.get("snapshot"), cursor);
    if (version !== requestVersion) return;
    state.view = view;
    if (isGraph) state.graphPage = view.query.page;
    history.replaceState(null, "", snapshotLink(location.hash || "#/search"));
    document.querySelector("#archive-snapshot").textContent = `SQLite 本地存储 · 已固定快照 ${view.snapshot_id}`;
    document.querySelectorAll(".primary-nav a, .brand").forEach((anchor) => { anchor.href = snapshotLink(anchor.getAttribute("href")); });
    render();
  } catch (error) {
    if (error.name === "AbortError" || version !== requestVersion) return;
    document.querySelector("#archive-snapshot").textContent = "档案未加载；没有回退到其他数据源。";
    replacePage(`<div class="empty-state" role="alert"><h2>档案暂未打开</h2><p>${escapeHtml(error.message)}</p><button id="retry" class="button">重新读取</button>${route().page === "search" ? '<button id="restart-search" class="button button-soft">从第一页重新检索</button>' : ""}</div>`);
    document.querySelector("#retry").addEventListener("click", () => loadView(cursor));
    if (route().page === "graph") {
      const link = document.createElement("a");
      link.className = "button";
      link.textContent = "返回默认中心与第一页";
      const parameters = new URLSearchParams(route().params);
      for (const field of ["center", "hops", "page", "layout", "predicate", "condition"]) parameters.delete(field);
      link.href = `#/graph?${parameters}`;
      main.append(link);
    }
    document.querySelector("#restart-search")?.addEventListener("click", () => loadView());
  }
}

function updateNavigation() {
  const current = route();
  document.querySelector("#page-name").textContent = pageNames[current.page] || "未找到页面";
  document.title = `${pageNames[current.page] || "未找到页面"} · 原神文本档案 · 原创样本`;
  document.querySelectorAll("[data-page]").forEach((anchor) => {
    if (anchor.dataset.page === current.page) anchor.setAttribute("aria-current", "page");
    else anchor.removeAttribute("aria-current");
  });
}

function render() {
  const current = route();
  updateNavigation();
  if (!state.view) return;
  try {
    if (current.page === "search") renderSearch();
    else if (current.page === "read") renderReader(state.view.target_id);
    else if (current.page === "graph") renderGraph(current.params.get("center"));
    else if (current.page === "characters") renderCharacters();
    else if (current.page === "character") renderCharacterDetail();
    else replacePage('<div class="empty-state"><h2>未找到这个页面</h2><a class="button" href="#/search">返回文本检索</a></div>');
  } catch (error) {
    replacePage(`<div class="empty-state" role="alert"><h2>无法展示当前样本</h2><p>${escapeHtml(error.message)}</p><a class="button" href="#/search">返回文本检索</a></div>`);
  }
}

function highlighted(text, query, mode) {
  const terms = (mode === "keywords" ? query.split(" ") : [query]).filter(Boolean);
  let markup = "";
  let position = 0;
  while (position < text.length) {
    const matches = terms.map((term) => ({ term, start: text.indexOf(term, position) })).filter((match) => match.start >= 0);
    matches.sort((left, right) => left.start - right.start || right.term.length - left.term.length);
    const match = matches[0];
    if (!match) return markup + escapeHtml(text.slice(position));
    markup += `${escapeHtml(text.slice(position, match.start))}<mark>${escapeHtml(match.term)}</mark>`;
    position = match.start + match.term.length;
  }
  return markup;
}

function renderSearch() {
  const view = state.view;
  const labels = characterLabels(view.characters);
  const results = view.results;
  const query = view.query.q;
  const pagination = view.pagination;
  const categoryNames = { quest: "任务文本" };
  const speakerLabel = (identifier) => identifier === "narration" ? "叙述" : labels.get(identifier);
  replacePage(`
    <section class="hero"><div class="eyebrow">READ THE WORDS. TRACE THE STORY.</div>
      <h1>从一句话，找到故事的来处。</h1><p>检索文本，回到上下文，沿证据探索人物关系。</p>
      <div class="hero-art" aria-hidden="true"><span>✦</span></div>
    </section>
    <form class="search-form" role="search"><span class="search-symbol" aria-hidden="true">⌕</span>
      <input id="search-input" aria-label="搜索原创样本文本" maxlength="200" placeholder="输入关键词或一句对白…" value="${escapeHtml(state.query)}">
      <button class="button button-primary" type="submit">检索文本 <span aria-hidden="true">→</span></button>
    </form>
    <div class="suggestions"><span>试着搜索</span>${["师父", "修桥", "先核对物资"].map((queryText) => `<button data-query="${queryText}">${queryText}</button>`).join("")}<span>服务端检索 · 仅返回当前页</span></div>
    <div class="search-filters" aria-label="搜索筛选">
      <label>匹配方式<select id="search-mode"><option value="literal" ${state.searchMode === "literal" ? "selected" : ""}>原句包含</option><option value="keywords" ${state.searchMode === "keywords" ? "selected" : ""}>关键词同时包含</option></select></label>
      <label>分类<select id="search-category"><option value="all">全部可用分类</option>${view.facets.categories.map((category) => `<option value="${escapeHtml(category.value)}" ${state.category === category.value ? "selected" : ""}>${escapeHtml(categoryNames[category.value] || category.value)} · ${category.count}</option>`).join("")}${state.category !== "all" && !view.facets.categories.some((category) => category.value === state.category) ? `<option value="${escapeHtml(state.category)}" selected>所选分类当前不可用</option>` : ""}</select></label>
      <label>说话人<select id="search-speaker"><option value="all">全部可用说话人</option>${view.facets.speakers.map((speaker) => `<option value="${escapeHtml(speaker.value)}" ${state.speaker === speaker.value ? "selected" : ""}>${escapeHtml(speakerLabel(speaker.value))} · ${speaker.count}</option>`).join("")}${state.speaker !== "all" && !view.facets.speakers.some((speaker) => speaker.value === state.speaker) ? `<option value="${escapeHtml(state.speaker)}" selected>所选说话人当前不可用</option>` : ""}</select></label>
      <label>每页<select id="search-limit">${[8, 16, 32].map((size) => `<option value="${size}" ${state.pageSize === size ? "selected" : ""}>${size} 条</option>`).join("")}</select></label>
      <button id="reset-search" class="text-button">清空查询与筛选</button>
    </div>
    <p class="search-help">关键词用空格分隔，须在同一段落同时出现；原句按连续文本包含匹配。分类与说话人数来自当前范围 / 用途，不随查询缩减。当前仅有原创任务样本。</p>
    <div class="stats-row" aria-label="当前范围统计">
      <div class="stat"><strong>${view.stats.passages}</strong><span>文本段落</span></div>
      <div class="stat"><strong>${view.stats.characters}</strong><span>样本人物</span></div>
      <div class="stat"><strong>${view.stats.relationships}</strong><span>有据关系</span></div>
      <div class="stat-label"><span class="status-dot"></span>当前范围 · 当前用途</div>
    </div>
    <div class="content-grid"><section id="search-results" tabindex="-1" aria-label="检索结果"><div class="section-heading"><h2>${query ? "检索结果" : "浏览文本"}</h2><span class="muted" role="status">${pagination.total} 个独立出现位置 · 本页 ${results.length} 条</span></div>
      <div class="result-list">${results.length ? results.map((passage, index) => `
        <article class="result"><span class="result-number">${String(pagination.offset + index + 1).padStart(2, "0")}</span><div class="result-body">
          <div class="result-meta">${tag(scopeLabel(passage))}<span class="result-title">${escapeHtml(view.entries.find((entry) => entry.id === passage.entry_id)?.title)}</span></div>
          <a class="result-text" href="${readLink(passage.id)}">${highlighted(passage.text, query, view.query.mode)}</a>
          <div class="result-bottom"><span>${escapeHtml(labels.get(passage.speaker_id) || passage.speaker_id || "叙述")} · <code>${escapeHtml(passage.id)}</code></span><a class="text-button" href="${readLink(passage.id)}">回到原文 ↗</a><button class="text-button" data-add-passage="${escapeHtml(passage.id)}">加入素材 ＋</button></div>
        </div></article>`).join("") : '<div class="empty-state"><div class="empty-symbol">⌕</div><h2>没有找到匹配的文本</h2><p>试试更短的关键词、清空筛选，或手动调整内容范围。不会自动打开后续内容。</p></div>'}</div>
      <nav class="search-pagination" aria-label="搜索结果分页"><button id="previous-page" class="button" ${pagination.previous_cursor ? "" : "disabled"}>← 上一页</button><span>第 ${pagination.page} / ${pagination.pages} 页</span><button id="next-page" class="button" ${pagination.next_cursor ? "" : "disabled"}>下一页 →</button></nav>
    </section><aside class="search-aside">${view.entries.length ? `<div class="aside-card"><div class="eyebrow">CURRENT PAGE ARCHIVE</div><div class="archive-stamp" aria-hidden="true">卷</div><h3>${escapeHtml(view.entries[0].title)}</h3><p>本页结果中的可用条目。沿着正文与完整证据，验证阅读与取材的每一步。</p>${tag("非原神剧情", "tag-warm")}<a class="button button-soft" href="${readLink(results[0].id)}">打开样本卷宗 ↗</a></div>` : ""}
      <div class="aside-info"><h3>文字之外，也有线索</h3><p>师徒、亲属、合作与对立。每条展示的关系，都能找到支持它的原文。</p><a class="text-button" href="#/graph">探索人物关系图 →</a><div class="inline-divider"></div><p>服务端先按范围与用途裁剪，再查询、计数和分页。翻页固定快照；可用内容变化会要求重新检索，不支持语义搜索。</p><code>${escapeHtml(view.snapshot_id)}</code></div>
    </aside></div>`);
  document.querySelector(".search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    state.query = document.querySelector("#search-input").value;
    state.searchQuery = state.query;
    loadView();
  });
  document.querySelector("#search-input").addEventListener("input", (event) => { state.query = event.target.value; });
  document.querySelectorAll("[data-query]").forEach((button) => button.addEventListener("click", () => {
    state.query = button.dataset.query;
    state.searchQuery = state.query;
    loadView();
  }));
  for (const [selector, key] of [["#search-mode", "searchMode"], ["#search-category", "category"], ["#search-speaker", "speaker"], ["#search-limit", "pageSize"]]) {
    document.querySelector(selector).addEventListener("change", (event) => {
      state[key] = key === "pageSize" ? Number(event.target.value) : event.target.value;
      state.searchQuery = state.query;
      loadView();
    });
  }
  document.querySelector("#reset-search").addEventListener("click", () => {
    Object.assign(state, { query: "", searchQuery: "", searchMode: "literal", category: "all", speaker: "all" });
    loadView();
  });
  for (const [selector, cursor] of [["#previous-page", pagination.previous_cursor], ["#next-page", pagination.next_cursor]]) {
    document.querySelector(selector).addEventListener("click", async () => {
      await loadView(cursor);
      const section = document.querySelector("#search-results");
      section?.focus({ preventScroll: true });
      section?.scrollIntoView({ block: "start" });
    });
  }
}

function renderCharacters() {
  const view = state.view;
  const labels = characterLabels(view.characters);
  const query = state.characterQuery.trim().toLocaleLowerCase();
  const filtered = view.characters.filter((character) => {
    const matchesQuery = !query || `${character.name} ${character.id}`.toLocaleLowerCase().includes(query);
    const hasProfile = ["element", "weapon", "faction", "rarity", "story"].some((field) => character[field]);
    return matchesQuery && (state.characterFilter === "all" || (state.characterFilter === "ready" ? hasProfile : !hasProfile));
  });
  const cards = filtered.map((character) => {
    const initial = escapeHtml((character.name || "?").slice(0, 1));
    const hasProfile = ["element", "weapon", "faction", "rarity", "story"].some((field) => character[field]);
    const profile = hasProfile
      ? `<dl class="character-facts">${["element", "weapon", "faction", "rarity"].filter((field) => character[field]).map((field) => `<div><dt>${({ element: "元素", weapon: "武器", faction: "阵营", rarity: "稀有度" })[field]}</dt><dd>${escapeHtml(character[field])}</dd></div>`).join("")}</dl><p>${escapeHtml(character.story || "角色故事待完成来源与授权核验。")}</p>`
      : `<p>当前只有稳定人物标识，未接入真实角色基本信息、立绘或角色故事。</p>`;
    return `<article class="character-card"><a class="character-card-link" href="#/character?id=${encodeURIComponent(character.id)}"><div class="character-portrait" aria-label="${escapeHtml(labels.get(character.id))}立绘占位"><span>${initial}</span><small>${hasProfile ? "资料已接入" : "立绘待授权"}</small></div></a><div class="character-card-body"><div class="eyebrow">${hasProfile ? "CHARACTER PROFILE" : "SYNTHETIC SAMPLE"}</div><h2>${escapeHtml(labels.get(character.id))}</h2><p class="character-id"><code>${escapeHtml(character.id)}</code></p>${profile}<a class="text-button" href="#/character?id=${encodeURIComponent(character.id)}">查看角色详情 →</a> <a class="text-button" href="${graphLink(character.id)}">查看关系证据 →</a></div></article>`;
  }).join("");
  replacePage(`<section class="characters-page"><div class="page-title-row"><div><div class="eyebrow">CHARACTER DIRECTORY</div><h1>先把人物放在一起。</h1></div><span class="tag tag-warm">${filtered.length} / ${view.characters.length} 个当前可见人物</span></div><div class="callout">这里展示的是当前快照中可见的角色记录。当前仓库只有原创合成样本；真实原神角色的基本信息、立绘和角色故事需要来源准入与批次核验后再接入。</div><div class="character-toolbar"><label>查找角色<input id="character-directory-query" maxlength="160" placeholder="姓名或角色 ID" value="${escapeHtml(state.characterQuery)}"></label><label>资料状态<select id="character-directory-filter"><option value="all" ${state.characterFilter === "all" ? "selected" : ""}>全部</option><option value="ready" ${state.characterFilter === "ready" ? "selected" : ""}>已有资料</option><option value="pending" ${state.characterFilter === "pending" ? "selected" : ""}>待接入</option></select></label></div><div class="character-grid">${cards || '<div class="empty-state">没有符合筛选条件的人物。</div>'}</div><p class="small muted">快照：${escapeHtml(view.snapshot_id)} · 角色目录最多读取 200 条。</p>${view.truncated ? '<div class="callout">角色数量超过当前读取上限，请缩小范围或继续完善分页接口。</div>' : ""}</section>`);
  document.querySelector("#character-directory-query").addEventListener("input", (event) => {
    state.characterQuery = event.target.value;
    const caret = event.target.selectionStart;
    renderCharacters();
    const input = document.querySelector("#character-directory-query");
    input.focus();
    input.setSelectionRange(caret, caret);
  });
  document.querySelector("#character-directory-filter").addEventListener("change", (event) => { state.characterFilter = event.target.value; renderCharacters(); });
}

function renderCharacterDetail() {
  const view = state.view;
  const character = view.character;
  const passages = view.passages || [];
  const relationships = view.relationships || [];
  const entries = view.entries || [];
  const sources = view.sources || [];
  const scopeNames = { opening: "开篇", east: "东路", west: "西路", later: "后续" };
  const predicateNames = { mentor_of: "师徒", parent_of: "亲属", opposes: "对立", cooperates_with: "合作" };
  const scopeSummary = ["opening", "east", "west", "later"].filter((scope) => (view.scope_ids || []).includes(scope)).map((scope) => scopeNames[scope]).join(" / ");
  const relationMarkup = relationships.length
    ? relationships.map((relation) => {
      const reviewLabel = relation.review_status === "approved" ? "已审核" : "待复核";
      const evidenceCount = (relation.evidence_groups || []).length;
      const relationScopeText = relation.branch_id ? `${scopeNames[relation.branch_id] || relation.branch_id}分支` : (relation.required_scope_ids || []).map((scope) => scopeNames[scope] || scope).join(" / ");
      return `<article class="character-relation"><div class="character-relation-top"><strong>${escapeHtml(predicateNames[relation.predicate] || relation.predicate)}</strong><span class="tag ${relation.review_status === "approved" ? "tag-blue" : "tag-warm"}">${reviewLabel}</span></div><p>${escapeHtml(relation.description || "关系描述待补充。")}</p><div class="character-relation-meta"><code>${escapeHtml(relation.id)}</code><span>范围：${escapeHtml(relationScopeText || "未标注")}</span><span>${evidenceCount} 组可见证据</span><a class="text-button" href="${graphRelationLink(character.id, relation.id)}">查看关系图 ↗</a></div></article>`;
    }).join("")
    : '<div class="empty-state">当前范围没有已审核关系。</div>';
  const entryMarkup = entries.length
    ? entries.map((entry) => `<li><strong>${escapeHtml(entry.title || entry.id)}</strong><code>${escapeHtml(entry.id)}</code></li>`).join("")
    : '<li class="muted">当前范围没有可见条目元数据。</li>';
  const sourceMarkup = sources.length
    ? sources.map((source) => {
      const allowed = source.rights?.display === "allowed";
      return `<li><div><strong>${escapeHtml(source.id)}</strong><span class="tag ${allowed ? "tag-blue" : "tag-warm"}">${allowed ? "允许展示" : "展示受限"}</span></div><code>${escapeHtml(source.locator || "未提供定位")}</code></li>`;
    }).join("")
    : '<li class="muted">当前范围没有可见来源元数据。</li>';
  replacePage(`<section class="character-detail-page"><a class="text-button" href="#/characters">← 返回角色目录</a><div class="character-detail-hero"><div class="character-portrait large"><span>${escapeHtml((character.name || "?").slice(0, 1))}</span><small>立绘待授权</small></div><div><div class="eyebrow">CHARACTER DETAIL · SYNTHETIC SAMPLE</div><h1>${escapeHtml(character.name)}</h1><code>${escapeHtml(character.id)}</code><p>当前只有稳定人物标识；真实角色基本信息、立绘和角色故事需要来源准入与批次核验后接入。</p><div class="character-detail-tags">${tag(`范围：${scopeSummary || "未标注"}`)}${tag(`快照：${view.snapshot_id}`)}</div><a class="button button-soft character-detail-graph-link" href="${graphLink(character.id)}">查看人物关系图 ↗</a></div></div><h2>当前可见对白</h2><p class="small muted">${passages.length} 段 · 仅显示当前范围、用途和快照允许的内容</p><div class="character-passages">${passages.length ? passages.map((passage) => `<blockquote><p>${escapeHtml(passage.text)}</p><footer>${escapeHtml(passage.id)} · <a class="text-button" href="${readLink(passage.id)}">回到原文 ↗</a></footer></blockquote>`).join("") : '<div class="empty-state">当前范围没有可见对白。</div>'}</div><h2>人物关系</h2><div class="character-relations">${relationMarkup}</div><div class="character-provenance"><div><h2>关联条目</h2><ul>${entryMarkup}</ul></div><div><h2>来源与用途</h2><ul>${sourceMarkup}</ul></div></div>${view.truncated ? '<div class="callout">关系或对白达到详情接口上限，当前页面未展示全部记录。请缩小范围或进入关系图继续查看。</div>' : ""}<div class="callout">角色故事、立绘和完整资料仍需授权来源与正文证据；当前页面只展示原创合成样本。</div></section>`);
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
    <div class="reader-layout"><article class="reading-paper"><header class="document-header"><div class="eyebrow">ORIGINAL SYNTHETIC FIXTURE / 001</div><h2>${escapeHtml(view.entries[0]?.title || "暂无可用条目")}</h2><div class="document-meta">${tag("原创测试 · 非原神剧情", "tag-warm")}<span>本页 ${passages.length} 段 · 当前范围共 ${view.pagination.total} 段</span><span>按显式对话连接排序</span></div></header>
      <div class="page-title-row"><button class="button button-soft" data-read-page="previous" ${view.pagination.previous_cursor ? "" : "disabled"}>上一页</button><span>第 ${Math.floor(view.pagination.offset / view.pagination.limit) + 1} 页</span><button class="button button-soft" data-read-page="next" ${view.pagination.next_cursor ? "" : "disabled"}>下一页</button></div>
      <div class="callout">只展示当前边界内的段落，缺失处不补写。两条分支分开展示，不代表同时发生；切换范围可单独阅读。</div>
      ${passages.map((passage) => {
        const section = scopeLabel(passage);
        const header = section !== previousSection ? `<h3 class="branch-heading">${escapeHtml(section)}</h3>` : "";
        previousSection = section;
        return `${header}<section class="passage ${passage.speaker_id ? "" : "narration"} ${passage.id === targetId ? "selected" : ""}" id="${escapeHtml(passage.id)}" tabindex="-1">
          <span class="passage-number">${escapeHtml(passage.id.split(":").at(-1))}</span><div class="passage-speaker">${escapeHtml(labels.get(passage.speaker_id) || passage.speaker_id || "叙述")}${passage.id === targetId ? tag("定位段落", "tag-warm") : ""}</div>
          <p>${escapeHtml(passage.text)}</p><div class="passage-actions"><code>${escapeHtml(passage.id)}</code><button class="text-button" data-copy="${escapeHtml(passage.id)}">复制引用 ↗</button><button class="text-button" data-add-passage="${escapeHtml(passage.id)}">加入素材 ＋</button><a class="text-button" href="${snapshotLink(`#/about?reference=${encodeURIComponent(passage.id)}`)}">纠错</a></div>
          <details class="passage-source"><summary>出处与对话连接</summary><code>${escapeHtml(passage.source_id)}<br>${escapeHtml(passage.source_locator)}</code><div>当前可见后续：${passage.next_ids.map((identifier) => `<a class="text-button" href="${readLink(identifier)}">${escapeHtml(identifier)}</a>`).join(" · ") || "无（不表示完整剧情结束）"}</div></details>
        </section>`;
      }).join("")}
    </article><aside class="reader-aside"><div class="aside-card"><div class="eyebrow">READ WITH CONTEXT</div><h3>一段话，不止一句。</h3><p>人物身份、发生分支和后续证据，都是理解一句对白的上下文。</p><div class="outline-list">${passages.filter((passage, index) => !index || scopeLabel(passage) !== scopeLabel(passages[index - 1])).map((passage) => `<button data-scroll="${escapeHtml(passage.id)}">${escapeHtml(scopeLabel(passage))} · ${escapeHtml(passage.id)}</button>`).join("")}</div></div><div class="aside-info"><h3>引用与使用边界</h3><p>复制前会重新核验导出用途。可读不等于可导出；快照变化时请先刷新。</p><code>${escapeHtml(view.snapshot_id)}</code></div></aside></div>`);
  document.querySelectorAll("[data-copy]").forEach((button) => button.addEventListener("click", () => copyCitation(button)));
  document.querySelectorAll("[data-read-page]").forEach((button) => button.addEventListener("click", () => loadView(view.pagination[`${button.dataset.readPage}_cursor`])));
  document.querySelectorAll("[data-scroll]").forEach((button) => button.addEventListener("click", () => focusPassage(button.dataset.scroll)));
  if (targetId && !unavailable) requestAnimationFrame(() => focusPassage(targetId));
}

function focusPassage(identifier) {
  const element = document.getElementById(identifier);
  if (route().page !== "read" || !element) return;
  element.scrollIntoView({ block: "center" });
  element.focus({ preventScroll: true });
}

function copyCitation(button) {
  return materialUI.citation(button.dataset.copy, button);
}

function restoreGraphQuery() {
  const params = route().params;
  state.center = params.get("center") || "person:student";
  state.hops = params.get("hops") || "1";
  state.predicate = params.get("predicate") || "all";
  state.condition = params.get("condition") || "all";
  state.graphPage = params.get("page") || "1";
  state.graphMode = params.get("mode") === "list" ? "list" : "graph";
  state.relation = params.get("relation") || null;
  graphLayout = null;
  try {
    const encoded = params.get("layout") || "null";
    if (encoded.length <= 12000) graphLayout = JSON.parse(encoded);
  } catch { /* Invalid saved positions are discarded, never interpreted as markup. */ }
}

function graphAddress({ shared = false, layout = null } = {}) {
  const params = new URLSearchParams({ center: state.center, hops: String(state.hops), predicate: state.predicate, condition: state.condition, page: String(state.graphPage), mode: state.graphMode });
  if (state.relation) params.set("relation", state.relation);
  if (shared) params.set("shared", "1");
  if (layout) params.set("layout", JSON.stringify(layout));
  return snapshotLink(`#/graph?${params}`);
}

function changeGraph(field, value) {
  const layout = field === "hops" ? captureLayout() || graphLayout : null;
  state[field] = value;
  state.relation = null;
  state.graphPage = 1;
  location.hash = graphAddress({ layout });
}

function renderGraph(requestedCenter) {
  const view = state.view;
  graphLayout = safeLayout(graphLayout, view.characters);
  state.hops = view.query.hops;
  state.graphPage = view.query.page;
  if (requestedCenter) state.center = requestedCenter;
  const labels = characterLabels(view.characters);
  const unavailable = !labels.has(state.center);
  const graph = { nodes: view.characters, edges: view.relationships, truncated: view.truncated };
  if (!graph.edges.some((relation) => relation.id === state.relation)) state.relation = graph.edges[0]?.id || null;
  replacePage(`
    <div class="page-title-row"><div><div class="eyebrow">PEOPLE, CONNECTED BY WORDS</div><h1>关系有据，故事有迹。</h1></div><div class="graph-actions"><button class="button" id="share-graph">复制分享链接</button><button class="button" id="export-png" ${state.graphMode === "list" ? "disabled" : ""}>导出 PNG</button><button class="button" id="export-graph">导出 JSON</button></div></div>
    ${route().params.has("shared") ? '<div class="callout">已恢复分享的快照和图谱条件；继续使用你当前选择的范围与用途。范围不足时仅展示允许内容，可在顶部手动调整。</div>' : ""}
    <form id="character-search" class="character-search"><label for="character-query">查找中心人物</label><input id="character-query" maxlength="160" placeholder="输入姓名或人物 ID"><button class="button" type="submit">查找</button><span id="character-status" role="status"></span></form>
    <div class="graph-toolbar"><label><span>中心人物</span><select id="graph-center" aria-label="中心人物">${unavailable ? '<option value="" selected>当前人物不可用</option>' : ""}${view.characters.map((character) => `<option value="${escapeHtml(character.id)}" ${character.id === state.center ? "selected" : ""}>${escapeHtml(labels.get(character.id))}</option>`).join("")}</select></label>
      <label><span>展开层级</span><select id="graph-hops" aria-label="展开层级"><option value="1" ${state.hops === 1 ? "selected" : ""}>一跳关系</option><option value="2" ${state.hops === 2 ? "selected" : ""}>二跳关系</option></select></label>
      <label><span>关系类型</span><select id="graph-predicate" aria-label="关系类型"><option value="all">全部类型</option>${Object.entries(PREDICATES).map(([key, value]) => `<option value="${key}" ${state.predicate === key ? "selected" : ""}>${value.label}</option>`).join("")}</select></label>
      <label><span>情节条件</span><select id="graph-condition" aria-label="情节条件"><option value="all">全部条件</option><option value="opening" ${state.condition === "opening" ? "selected" : ""}>开篇公共</option><option value="east" ${state.condition === "east" ? "selected" : ""}>东路分支</option><option value="west" ${state.condition === "west" ? "selected" : ""}>西路分支</option><option value="later" ${state.condition === "later" ? "selected" : ""}>后续阶段</option></select></label>
      <span class="toolbar-spacer"></span><div class="segmented" aria-label="图谱展示方式"><button data-mode="graph" aria-pressed="${state.graphMode === "graph"}">图谱</button><button data-mode="list" aria-pressed="${state.graphMode === "list"}">列表</button></div>
    </div>
    ${unavailable ? '<div class="callout" role="alert">当前人物在此范围、用途或快照中不可用。请选择一个可见人物，不会自动扩大范围。</div>' : ""}
    ${graph.truncated ? '<div class="callout">当前视图未完整展示：每页最多 50 个人物 / 100 条关系。使用下方分页继续查看，或缩小筛选范围。</div>' : ""}
    <div class="graph-layout"><section class="graph-stage" aria-label="人物关系"><div class="graph-topline"><strong>${graph.nodes.length} 个人物 · ${graph.edges.length} 条关系</strong><span>当前页关系 · 证据完整</span></div>
      ${state.graphMode === "graph" ? '<div class="graph-canvas"><svg id="relationship-svg" role="group" aria-label="局部人物关系图，Tab 可选择人物或关系"></svg><span class="graph-watermark">SYNTHETIC STORY / NOT GAME LORE</span><div class="graph-controls"><button data-zoom="out" aria-label="缩小图谱">−</button><span id="zoom-level">100%</span><button data-zoom="in" aria-label="放大图谱">+</button><button data-zoom="reset" aria-label="重置布局">↺</button></div></div>' : `<div class="relationship-list"><div class="list-nodes" aria-label="当前页人物">${graph.nodes.map((node) => `<a class="button button-soft" href="${characterDetailLink(node.id)}">${escapeHtml(labels.get(node.id))}${node.id === state.center ? " · 中心" : ""}</a>`).join("")}</div>${graph.edges.length ? graph.edges.map((relation) => `<button class="relationship-row" data-relation="${escapeHtml(relation.id)}" aria-pressed="${relation.id === state.relation}"><strong>${escapeHtml(labels.get(relation.from_id))} ${relation.direction === "directed" ? "→" : "—"} ${escapeHtml(labels.get(relation.to_id))}</strong><span>${PREDICATES[relation.predicate].label} · ${escapeHtml(relationScope(relation, view.passages))}</span></button>`).join("") : '<div class="empty-state">当前条件下没有可用关系。可切换中心人物或筛选条件。</div>'}</div>`}
      <div class="graph-legend">${Object.values(PREDICATES).map((predicate) => `<span><i class="legend-line" style="--relation-color:${predicate.color}"></i>${predicate.label}</span>`).join("")}<span>→ 有向关系　— 对称关系</span></div>
    </section><aside class="evidence-panel" id="evidence-panel" aria-label="关系证据" aria-live="polite"></aside></div>
    <div class="pagination"><button id="graph-previous" class="button" ${view.pagination.previous_cursor ? "" : "disabled"}>上一页</button><span>局部图第 ${view.pagination.page} / ${view.pagination.pages} 页</span><button id="graph-next" class="button" ${view.pagination.next_cursor ? "" : "disabled"}>下一页</button><button id="graph-restart" class="button">重新读取第一页</button></div>
    <div class="graph-footnote"><p>点击连线查看原文证据；拖动人物调整位置，拖动画布平移，使用 + / − 缩放。键盘可选择连线；人物按 Enter 设为中心。</p><p>分支与后续证据分别标注，不把共现当作关系，也不把不同分支当作同一时刻。这里只演示原创样本。</p></div>`);
  document.querySelector("#graph-center").addEventListener("change", (event) => { changeGraph("center", event.target.value); });
  document.querySelector("#graph-hops").addEventListener("change", (event) => { changeGraph("hops", Number(event.target.value)); });
  document.querySelector("#graph-predicate").addEventListener("change", (event) => { changeGraph("predicate", event.target.value); });
  document.querySelector("#graph-condition").addEventListener("change", (event) => { changeGraph("condition", event.target.value); });
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => { graphLayout = captureLayout() || graphLayout; state.graphMode = button.dataset.mode; history.replaceState(null, "", graphAddress({ layout: graphLayout })); renderGraph(); }));
  document.querySelectorAll("[data-relation]").forEach((button) => button.addEventListener("click", () => selectRelation(button.dataset.relation)));
  document.querySelector("#export-graph").addEventListener("click", (event) => exportGraph(event.currentTarget));
  document.querySelector("#export-png").addEventListener("click", (event) => exportGraph(event.currentTarget, "png"));
  document.querySelector("#share-graph").addEventListener("click", shareGraph);
  document.querySelector("#character-search").addEventListener("submit", searchCharacters);
  for (const direction of ["previous", "next"]) document.querySelector(`#graph-${direction}`).addEventListener("click", () => {
    state.graphPage += direction === "next" ? 1 : -1;
    history.replaceState(null, "", graphAddress());
    loadView(view.pagination[`${direction}_cursor`]);
  });
  document.querySelector("#graph-restart").addEventListener("click", () => {
    state.graphPage = 1; history.replaceState(null, "", graphAddress()); loadView();
  });
  if (state.relation) selectRelation(state.relation);
  else renderEvidence(null);
  if (state.graphMode === "graph") mountGraph(graph, labels);
}

async function selectRelation(identifier) {
  state.relation = identifier;
  history.replaceState(null, "", graphAddress());
  const version = ++evidenceVersion;
  const original = state.view;
  document.querySelectorAll(".graph-edge, .relationship-row").forEach((element) => {
    element.classList.toggle("selected", element.dataset.relation === identifier);
    element.setAttribute("aria-pressed", String(element.dataset.relation === identifier));
  });
  const panel = document.querySelector("#evidence-panel");
  panel.textContent = "正在重新核验完整证据…";
  try {
    const details = await fetchArchive("/api/relationship", purposeSelect.value, requestController.signal, original.snapshot_id, { id: identifier });
    if (version !== evidenceVersion || original !== state.view || !panel.isConnected) return;
    if (JSON.stringify(details.relationships[0]) !== JSON.stringify(original.relationships.find((item) => item.id === identifier))) throw new Error("关系证据已变化，请重新读取图谱。");
    renderEvidence(details.relationships[0], details);
  } catch (error) {
    if (error.name !== "AbortError" && version === evidenceVersion && panel.isConnected) panel.textContent = error.message;
  }
}

function renderEvidence(relation, view = state.view) {
  const panel = document.querySelector("#evidence-panel");
  if (!relation) {
    panel.innerHTML = '<div class="eyebrow">FOLLOW THE EVIDENCE</div><h2>等待一条有据的连线</h2><p class="small muted">当前局部图没有可用关系。不会用人物共现或 AI 猜测补齐。</p>';
    return;
  }
  const labels = characterLabels(view.characters);
  const relationSource = (view.sources || []).find((source) => source.id === relation.source_id);
  const relationSourceLocator = relationSource?.locator || "来源定位未标注";
  const person = (identifier) => `<a class="relation-person" href="${characterDetailLink(identifier)}">${escapeHtml(view.characters.find((character) => character.id === identifier)?.name)}<small>${escapeHtml(identifier)}</small></a>`;
  const reviewLabel = relation.review_status === "approved" ? "已审核" : relation.review_status === "pending" ? "待复核" : "审核状态未标注";
  const reviewStyle = relation.review_status === "approved" ? "tag-blue" : "tag-warm";
  const claimLabel = relation.claim_kind === "explicit" ? "明确断言" : relation.claim_kind === "inferred" ? "推断关系" : "断言类型未标注";
  panel.innerHTML = `<div class="eyebrow">FOLLOW THE EVIDENCE</div><h2>关系与原文证据</h2><div class="relation-people">${person(relation.from_id)}<span class="relation-arrow">${relation.direction === "directed" ? "→" : "—"}</span>${person(relation.to_id)}</div>
    ${tag(PREDICATES[relation.predicate].label)} ${tag(reviewLabel, reviewStyle)} ${tag(claimLabel)}<p class="relation-description">${escapeHtml(relation.description)}</p><p class="small muted">${escapeHtml(relationScope(relation, view.passages))}</p>
    ${relation.evidence_groups.map((group, index) => `<div class="evidence-group-label">证据组 ${index + 1} · ${group.length > 1 ? `${group.length} 段须联合阅读` : "单段支持"}</div>${group.map((identifier) => {
      const passage = view.passages.find((candidate) => candidate.id === identifier);
      return `<blockquote class="evidence-quote"><p>${escapeHtml(passage.text)}</p><footer><span>${escapeHtml(labels.get(passage.speaker_id) || passage.speaker_id || "叙述")} · ${escapeHtml(scopeLabel(passage))}</span><a class="text-button" href="${readLink(identifier)}">${escapeHtml(identifier)} · 回到原文 ↗</a><code>${escapeHtml(passage.source_id)} · ${escapeHtml(passage.source_locator)}</code></footer></blockquote>`;
    }).join("")}`).join("")}
    <button class="button button-soft" id="add-relation-material">关系与证据加入素材 ＋</button><a class="text-button" href="${snapshotLink(`#/about?reference=${encodeURIComponent(relation.id)}&kind=relationship`)}">纠正这条关系</a>
    <div class="evidence-note">组内段落须共同成立；不同完整证据组可独立支持同一断言。样本断言不等于原神设定。</div><div class="evidence-footer"><code>关系 ID：${escapeHtml(relation.id)}<br>关系断言来源：${escapeHtml(relation.source_id || "来源 ID 未标注")}<br>关系来源定位：${escapeHtml(relationSourceLocator)}<br>快照：${escapeHtml(view.snapshot_id)}</code></div>`;
  document.querySelector("#add-relation-material").addEventListener("click", (event) => materialUI.add("relationship", relation.id, event.currentTarget));
}

async function searchCharacters(event) {
  event.preventDefault();
  const original = state.view;
  const input = document.querySelector("#character-query");
  const query = input.value.trim();
  const status = document.querySelector("#character-status");
  status.textContent = "查找中…";
  try {
    const found = await fetchArchive("/api/characters", purposeSelect.value, requestController.signal, original.snapshot_id, { q: query });
    if (original !== state.view || !input.isConnected || input.value.trim() !== query) return;
    const labels = characterLabels(found.characters);
    const select = document.querySelector("#graph-center");
    select.innerHTML = '<option value="" disabled selected>选择查找到的人物</option>' + found.characters.map((character) => `<option value="${escapeHtml(character.id)}">${escapeHtml(labels.get(character.id))}</option>`).join("");
    status.textContent = found.truncated ? "只显示前 20 个匹配，请细化姓名或 ID。" : `找到 ${found.characters.length} 个人物`;
  } catch (error) { if (error.name !== "AbortError" && status.isConnected) status.textContent = error.message; }
}

async function checkedGraph(purpose) {
  const original = state.view;
  const version = requestVersion;
  const view = await fetchArchive("/api/graph", purpose, requestController.signal, original.snapshot_id, original.query);
  if (original !== state.view || version !== requestVersion) throw new Error("范围或图谱选择已变化，请重新操作。");
  if (view.content_revision !== original.content_revision) throw new Error("图谱或完整证据已变化，或含不可导出内容。请切换「素材导出」用途并重新读取后重试。");
  return view;
}

async function shareGraph(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await checkedGraph(purposeSelect.value);
    if (!button.isConnected) return;
    const address = new URL(graphAddress({ shared: true, layout: safeLayout(captureLayout() || graphLayout, state.view.characters) }), location.href);
    await navigator.clipboard.writeText(address.href);
    notify("已复制本机分享链接；恢复图谱参数与布局，不会自动扩大接收者范围。");
  } catch (error) { if (error.name !== "AbortError") notify(error.message); }
  finally { button.disabled = false; }
}

function downloadGraph(blob, extension) {
  const address = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = address; anchor.download = `synthetic-character-graph.${extension}`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(address), 1000);
}

async function exportGraph(button, format = "json") {
  button.disabled = true;
  try {
    if (purposeSelect.value !== "export") await checkedGraph(purposeSelect.value);
    const view = await checkedGraph("export");
    if (!button.isConnected) throw new Error("图谱选择已经变化，请重新导出。");
    if (format === "png") {
      const blob = await graphPng(view);
      await checkedGraph("export");
      if (!button.isConnected) throw new Error("图谱选择已经变化，请重新导出。");
      downloadGraph(blob, "png");
    } else {
      const { pagination, ...output } = view;
      output.pagination = { page: pagination.page, pages: pagination.pages };
      output.layout = safeLayout(captureLayout() || graphLayout, view.characters);
      downloadGraph(new Blob([JSON.stringify(output, null, 2)], { type: "application/json" }), "json");
    }
    notify(`已导出当前局部图 ${format.toUpperCase()}，保留快照、范围和原创样本标识。`);
  } catch (error) { if (error.name !== "AbortError") notify(error.message || "图像生成失败，请重试。"); }
  finally { button.disabled = false; }
}

async function graphPng(view) {
  const svg = document.querySelector("#relationship-svg");
  if (!svg) throw new Error("请切换到图谱视图后导出 PNG。");
  const clone = svg.cloneNode(true);
  const originals = [svg, ...svg.querySelectorAll("*")];
  const copies = [clone, ...clone.querySelectorAll("*")];
  const properties = ["fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "font-size", "font-family", "font-weight", "text-anchor", "dominant-baseline", "paint-order"];
  originals.forEach((element, index) => {
    const style = getComputedStyle(element);
    properties.forEach((property) => copies[index].style.setProperty(property, style.getPropertyValue(property)));
  });
  clone.setAttribute("x", "0"); clone.setAttribute("y", "90"); clone.setAttribute("width", "1200"); clone.setAttribute("height", "630");
  const scopeNames = { opening: "开篇", east: "东路", west: "西路", later: "后续" };
  const caption = `范围：${view.scope_ids.map((scope) => scopeNames[scope] || scope).join(" / ")} · ${view.characters.length} 人物 / ${view.relationships.length} 关系 · 第 ${view.pagination.page}/${view.pagination.pages} 页 · ${view.truncated ? "当前视图未完整展示" : "当前局部图完整"}`;
  const legend = Object.values(PREDICATES).map((predicate, index) => `<text x="${35 + index * 155}" y="762" fill="${predicate.color}">${predicate.label}</text>`).join("");
  const xml = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#f7f5ec"/><g font-family="sans-serif" fill="#263e30"><text x="30" y="30" font-size="20">人物局部图 · 原创合成样本，非原神剧情</text><text x="30" y="55" font-size="14">快照：${escapeHtml(view.snapshot_id)}</text><text x="30" y="78" font-size="14">${escapeHtml(caption)}</text></g>${new XMLSerializer().serializeToString(clone)}<g font-family="sans-serif" font-size="17">${legend}<text x="660" y="762" fill="#263e30">→ 有向关系　— 对称关系</text><text x="35" y="790" font-size="12" fill="#52624e">图中位置不代表亲密程度；关系适用条件和完整证据见同视图 JSON。</text></g></svg>`;
  const address = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const image = new Image();
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error("无法生成 PNG 图像。")); image.src = address; });
    const canvas = document.createElement("canvas"); canvas.width = 1200; canvas.height = 800;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return await new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG 编码失败。")), "image/png"));
  } finally { URL.revokeObjectURL(address); }
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

  function reset(saved = null) {
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
    if (saved && typeof saved === "object" && saved.positions && typeof saved.positions === "object") {
      for (const node of graph.nodes) {
        const point = saved.positions[node.id];
        if (Array.isArray(point) && point.length === 2 && point.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)) positions.set(node.id, { x: point[0] * width, y: point[1] * height });
      }
      if (Number.isFinite(saved.scale) && saved.scale >= .6 && saved.scale <= 1.8) scale = saved.scale;
      if (Array.isArray(saved.pan) && saved.pan.length === 2 && saved.pan.every((value) => Number.isFinite(value) && Math.abs(value) <= 3)) pan = { x: saved.pan[0] * width, y: saved.pan[1] * height };
    }
    draw();
  }

  captureLayout = () => ({ positions: Object.fromEntries(graph.nodes.map((node) => { const point = positions.get(node.id); return [node.id, [Math.round(point.x / width * 10000) / 10000, Math.round(point.y / height * 10000) / 10000]]; })), scale, pan: [Math.max(-3, Math.min(3, pan.x / width)), Math.max(-3, Math.min(3, pan.y / height))] });

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
  const observer = new ResizeObserver(() => reset(captureLayout()));
  observer.observe(container);
  pageCleanup = () => { observer.disconnect(); captureLayout = () => null; };
  reset(graphLayout);
  graphLayout = captureLayout();
}

async function renderAbout() {
  const version = requestVersion;
  const params = route().params;
  if (params.has("reference") && !feedbackDraft.description) {
    feedbackDraft.reference = params.get("reference").slice(0, 160);
    feedbackDraft.snapshot = params.get("snapshot") || "";
    feedbackDraft.kind = params.get("kind") === "relationship" ? "relationship" : "text";
  }
  let status = null;
  try { status = await fetchArchive("/api/status", purposeSelect.value, requestController.signal, params.get("snapshot")); }
  catch (error) { if (error.name === "AbortError") return; }
  if (version !== requestVersion) return;
  if (status) {
    state.view = status;
    document.querySelector("#archive-snapshot").textContent = `当前收录快照 · ${status.snapshot_id}`;
    if (!feedbackDraft.snapshot) feedbackDraft.snapshot = status.snapshot_id;
  } else document.querySelector("#archive-snapshot").textContent = "收录快照暂不可用；仍可提交本地问题反馈。";
  const kinds = { text: "文本错误", attribution: "归属错误", branch: "分支问题", relationship: "人物关系错误", missing: "内容缺漏", usage: "内容使用问题" };
  const admission = status?.source_admission;
  const admissionRows = admission?.sources?.map((source) => `<li><div><strong>${escapeHtml(source.source_id)}</strong><span class="small">申请：${escapeHtml(source.requested_uses.join("、"))}</span></div><span class="tag ${source.ready ? "tag-blue" : "tag-warm"}">${source.ready ? "已准入" : "待确认"}</span><p>${source.ready ? "授权字段已满足当前申请用途。" : `缺口：${escapeHtml(source.missing_requirements.join("、") || source.unapproved_uses.join("、") || "需复核")}`}</p><ol class="source-next-actions">${(source.next_actions || []).map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ol></li>`).join("") || "";
  replacePage(`<section class="about-page"><div class="eyebrow">SOURCES & CORRECTIONS</div><h1>知道收录了什么，也能指出问题。</h1>
    <div class="callout">当前全部内容为原创合成样本，不是原神剧情。真实来源准入与剧情准确性尚未验收。</div>
    <h2>收录与已知缺口</h2><p>当前读取：<code>${escapeHtml(status?.snapshot_id || params.get("snapshot") || "暂不可用")}</code>。页面只展示顶部范围与用途允许的内容。</p>
    <p>当前收录的是用于验证对白、分支和关系证据的原创结构样本；只展示当前允许且已审核的内容。BWIKI、观测枢和空荧酒馆目前仅有候选来源记录，尚未接入真实正文。</p>
    <h2>真实来源准入状态</h2><p>以下仅显示来源元数据和用途缺口，不读取或展示真实正文。来源获准后仍需单独完成批次、出处和数据契约核验。</p><ul class="source-admission-list">${admissionRows || "<li>准入状态暂不可用。</li>"}</ul>
    <p>没有公开部署、语义检索或实时撤下通知。AI 只读连接需维护者显式启用，网站不会自动调用外部模型。下载文件不会自动更新；使用前请重新核验。反馈提交仅进入本机维护收件箱，不对外公开。</p>
    <h2>更新摘要 · 2026-10-12</h2><p>已完成固定快照存储、搜索、局部关系图及素材清单。本轮新增可下载的剧情创作 Skill，支持本地只读取材和离线素材校验，已完成合成资料创作试用。</p>
    <h2>剧情创作 Skill</h2><p>下载可移植工作流，使用本地只读连接或经用途检查的 JSON 素材包。当前只验证原创合成资料，安装技能包不会自动开启连接或调用模型。</p>
    <a class="button" href="/downloads/genshin-story-writer.zip" download="genshin-story-writer.zip">下载剧情创作 Skill ZIP</a>
    <p class="small">包内含创作说明、工具约定和 Python 客户端。解压后由支持技能文件的助手读取 SKILL.md；在“AI 取材”用途下导出的素材包可用于离线流程。</p>
    <h2>提交纠错</h2><p>问题写入本机维护者可读取的收件箱；成功后返回编号。尚未承诺处理时限。请填写必要说明，可不提供联系信息。</p>
    <form id="feedback-form" class="feedback-form">
      <label>问题类型<select name="kind">${Object.entries(kinds).map(([key, label]) => `<option value="${key}" ${feedbackDraft.kind === key ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
      <label>相关快照<input name="snapshot" maxlength="160" value="${escapeHtml(feedbackDraft.snapshot)}"></label>
      <label>段落 / 关系 ID（可选）<input name="reference" maxlength="160" value="${escapeHtml(feedbackDraft.reference)}"></label>
      <label>问题说明<textarea name="description" rows="5" maxlength="4000" required>${escapeHtml(feedbackDraft.description)}</textarea></label>
      <label>联系信息（可选，仅本机维护者可见）<input name="contact" maxlength="200" autocomplete="off" value="${escapeHtml(feedbackDraft.contact)}"></label>
      <button class="button button-primary" type="submit">提交至本地收件箱</button><p id="feedback-status" role="status"></p>
    </form></section>`);
  const form = document.querySelector("#feedback-form");
  form.addEventListener("input", () => { Object.assign(feedbackDraft, Object.fromEntries(new FormData(form))); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]'); button.disabled = true;
    const message = form.querySelector('#feedback-status'); message.textContent = "正在保存反馈…";
    if (feedbackAttempt && feedbackAttempt !== JSON.stringify(feedbackDraft)) feedbackDraft.request_id = crypto.randomUUID();
    const payload = { ...feedbackDraft };
    feedbackAttempt = JSON.stringify(payload);
    try {
      const response = await postJson('/api/feedback', payload);
      if (JSON.stringify(payload) === JSON.stringify(feedbackDraft)) {
        feedbackDraft = { ...feedbackDraft, request_id: crypto.randomUUID(), description: '', contact: '' };
        if (form.isConnected) { form.elements.description.value = ''; form.elements.contact.value = ''; }
      } else feedbackDraft.request_id = crypto.randomUUID();
      if (form.isConnected) message.textContent = `已保存至本地维护收件箱。编号：${response.id}；尚未人工处理。`;
      else notify(`反馈已保存，编号：${response.id}`);
    } catch (error) { if (form.isConnected) message.textContent = error.message + " 说明和联系信息仍保留，可重试。"; }
    finally { button.disabled = false; }
  });
}

function changeBoundary() {
  state.searchQuery = state.query;
  if (route().page === "graph") {
    state.graphPage = 1;
    history.replaceState(null, "", graphAddress());
  } else history.replaceState(null, "", snapshotLink(location.hash || "#/search"));
  loadView();
}
scopeSelect.addEventListener("change", changeBoundary);
purposeSelect.addEventListener("change", changeBoundary);
window.addEventListener("hashchange", () => {
  loadView();
  window.scrollTo(0, 0);
});
document.querySelector("#open-active").addEventListener("click", () => {
  history.replaceState(null, "", "#/search");
  loadView();
});
window.addEventListener("storage", (event) => {
  if (event.key === "story-archive-materials-v1" || event.key === null) {
    if (route().page === "materials") loadView();
    else notify("素材清单已在另一个页面更新，下次操作将重新核验。");
  }
});
document.querySelector(".skip-link").addEventListener("click", (event) => { event.preventDefault(); main.focus(); });
loadView();
