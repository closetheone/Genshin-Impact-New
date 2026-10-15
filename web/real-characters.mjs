const escape = (value) => String(value ?? "").replace(/[&<>"']/gu, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fields = { element: "元素", weapon: "武器", rarity: "稀有度", region: "地区", affiliation: "所属组织", birthday: "生日", constellation: "命之座" };
const valueLabel = (value) => value === null || value === "" || value === undefined ? "来源未提供" : String(value);
const elementLabel = (value) => value === "无" ? "无固定元素（来源标注）" : value;
const facts = (character, keys = Object.keys(fields)) => `<dl class="character-facts">${keys.map((key) => `<div><dt>${fields[key]}</dt><dd>${escape(key === "element" ? elementLabel(character[key]) : valueLabel(character[key]))}${key === "rarity" ? " 星" : ""}</dd></div>`).join("")}</dl>`;
const officialReference = (data, character) => data.official_links?.status === "available"
  ? data.official_links.records.find((record) => record.character_id === character.id && record.name === character.name) : null;
const officialButton = (record, compact = false) => `<a class="${compact ? "text-button" : "button button-primary"}" href="${escape(record.url)}" target="_blank" rel="noopener noreferrer">${compact ? "官网立绘与简介" : `前往官网查看${escape(record.name)}`} ↗</a>`;

export function portraitHTML(data, character, large = false) {
  const record = data.official_art?.status === "available"
    ? data.official_art.records.find((r) => r.character_id === character.id && r.name === character.name) : null;
  const classes = `character-portrait real-portrait${large ? " large" : ""}`;
  if (!record) return `<div class="${classes}" data-element="${escape(character.element)}"><span>${escape(character.name.slice(0, 1))}</span><small>${data.official_art?.status === "available" ? "暂无匹配图片 · 文字占位" : "图片资料暂不可用 · 文字占位"}</small></div>`;
  return `<div class="${classes} official-portrait" data-element="${escape(character.element)}" data-portrait-state="loading" aria-busy="true">
    <img src="${escape(large ? record.portrait_url : record.thumbnail_url)}" alt="${escape(character.name)} · 官网${large ? "立绘" : "头像"}" loading="${large ? "eager" : "lazy"}" decoding="async" referrerpolicy="no-referrer">
    <div class="portrait-placeholder"><span aria-hidden="true">${escape(character.name.slice(0, 1))}</span><small data-portrait-status>图片加载中…</small>${large ? '<button class="button" data-portrait-retry hidden>重新加载图片</button>' : ""}</div>
    <small class="portrait-credit">官网图片 · ${escape(data.official_art.copyright)}${large ? ` · <a href="${escape(record.source_url)}" target="_blank" rel="noopener noreferrer">来源 ↗</a> · <a href="${escape(record.portrait_url)}" target="_blank" rel="noopener noreferrer">查看大图 ↗</a>` : ""}</small>
  </div>`;
}

export function bindPortraits(root = document) {
  for (const frame of root.querySelectorAll('[data-portrait-state]')) {
    const img = frame.querySelector('img');
    const status = frame.querySelector('[data-portrait-status]');
    const retry = frame.querySelector('[data-portrait-retry]');
    const update = (state) => {
      frame.dataset.portraitState = state;
      frame.setAttribute('aria-busy', String(state === 'loading'));
      status.textContent = state === 'error' ? '图片暂不可用，可通过官网入口查看' : '图片加载中…';
      if (retry) retry.hidden = state !== 'error';
    };
    img.addEventListener('load', () => update('loaded'));
    img.addEventListener('error', () => update('error'));
    retry?.addEventListener('click', () => {
      update('loading');
      const url = img.getAttribute('src');
      img.removeAttribute('src');
      img.setAttribute('src', url);
    });
    // Cached images can finish before these handlers are attached.
    if (img.complete) update(img.naturalWidth > 0 ? 'loaded' : 'error');
  }
}

function officialPanel(data, character) {
  const record = officialReference(data, character);
  return `<section class="official-character-panel" aria-label="官方角色展示"><h2>官方角色展示</h2>${record
    ? `<p>前往《原神》官网查看${escape(character.name)}的立绘、官方简介和配音。</p>${officialButton(record)}<p class="small muted">将在新标签页打开官网 · ${escape(record.section)} · 入口核对于 ${escape(data.official_links.checked_on)}<br>官网可能调整角色顺序；若显示了其他角色，请在官网下方角色栏选择「${escape(character.name)}」。</p>`
    : `<p>${data.official_links?.status === "available" ? "尚未匹配到此角色的官网展示入口。" : "官网展示入口暂不可用，基础资料仍可查看。"}</p>`}</section>`;
}

export function catalogPage(characters, { query = "", element = "all", region = "all", page = 1 } = {}) {
  const term = query.trim().toLocaleLowerCase();
  const filtered = characters.filter((character) => (element === "all" || character.element === element)
    && (region === "all" || (region === "missing" ? !character.region : character.region === region))
    && [character.name, character.region, character.affiliation, character.weapon, character.slug].filter(Boolean).join(" ").toLocaleLowerCase().includes(term));
  const pages = Math.max(1, Math.ceil(filtered.length / 24));
  const current = Math.min(pages, Math.max(1, Number.isSafeInteger(page) ? page : 1));
  return { records: filtered.slice((current - 1) * 24, current * 24), total: filtered.length, pages, page: current };
}

export function catalogAddress(catalog, id, selection = {}) {
  const params = new URLSearchParams({ catalog, ...(id ? { id } : {}) });
  if (selection.query) params.set("q", selection.query);
  if (selection.element && selection.element !== "all") params.set("element", selection.element);
  if (selection.region && selection.region !== "all") params.set("region", selection.region);
  if (selection.page > 1) params.set("page", String(selection.page));
  return `#/real-${id ? "character" : "characters"}?${params}`;
}

export async function loadRealCharacters(params, detail, signal) {
  const query = new URLSearchParams();
  if (params.has("catalog")) query.set("catalog", params.get("catalog"));
  if (detail) query.set("character", params.get("id") || "");
  const response = await fetch(`/api/character-catalog?${query}`, { signal, cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "真实角色资料读取失败。");
  if (data.dataset_kind !== "real_character_facts") throw new Error("资料类型不匹配，未替换为样本。");
  return data;
}

export function renderRealCharacters(data, detail, replacePage, params = new URLSearchParams()) {
  const catalog = data.catalog_id;
  const selection = { query: (params.get("q") || "").slice(0, 160), element: params.get("element") || "all", region: params.get("region") || "all", page: /^\d{1,5}$/u.test(params.get("page") || "") ? Number(params.get("page")) : 1 };
  const source = `<p class="small muted">数据整理：${escape(data.source.name)} · 核对日期：${escape(data.checked_on)}<br>资料批次：<code>${escape(catalog)}</code> · 来源版本：<code>${escape(data.source.revision.slice(0, 12))}</code></p>`;
  const coverage = data.coverage ? `已收录固定来源目录的全部 ${data.coverage.record_count} 条角色记录。此社区资料版本不等于官方当前已实装角色名单。` : "这是保留的首批四角色资料版本。";
  if (detail) {
    const character = data.character;
    history.replaceState(null, "", catalogAddress(catalog, character.id, selection));
    replacePage(`<section class="character-detail-page real-character-page"><a class="text-button" href="${catalogAddress(catalog, null, selection)}">← 返回真实角色目录</a> · <a class="text-button" href="#/real-characters">打开最新目录 →</a>
      <div class="character-detail-hero real-character-hero">${portraitHTML(data, character, true)}<div><div class="eyebrow">GENSHIN IMPACT · CHARACTER PROFILE</div><h1>${escape(character.name)}</h1><p>${escape(valueLabel(character.region))} · ${escape(valueLabel(character.affiliation))}</p><span class="tag tag-blue">角色基础资料 · 社区来源</span>${facts(character)}</div></div>
      ${officialPanel(data, character)}
      <h2>角色故事</h2><p>游戏内完整角色故事与对白尚未收录，官网简介不等于完整角色故事。当前没有已核验的人物关系记录。</p>
      <h2>资料出处</h2>${source}<p class="small muted">${coverage} 未提供的字段不做推测补齐；“无”元素按来源保留，不展开成多个角色。</p><p><a class="button button-soft" href="${escape(character.provenance.url)}" target="_blank" rel="noopener noreferrer">查看此角色的来源记录 ↗</a> <a class="text-button" href="${escape(data.source.license_url)}" target="_blank" rel="noopener noreferrer">仓库许可说明 ↗</a></p>
      <details class="real-provenance"><summary>字段定位与核对记录</summary><dl>${Object.entries(character.provenance.fields).map(([field, original]) => `<dt>${escape(fields[field] || "角色名")}</dt><dd><code>/${escape(original)}</code></dd>`).join("")}</dl><p>来源文件 SHA-256：<code>${escape(character.provenance.sha256)}</code></p></details><p class="small muted">${escape(data.source.scope)}</p></section>`);
    bindPortraits();
    return;
  }
  const elements = [...new Set(data.characters.map((c) => c.element))];
  const regions = [...new Set(data.characters.map((c) => c.region).filter(Boolean))];
  if (!elements.includes(selection.element)) selection.element = "all";
  if (!regions.includes(selection.region) && selection.region !== "missing") selection.region = "all";
  const options = (values, selected, label = (value) => value) => values.map((value) => `<option value="${escape(value)}" ${selected === value ? "selected" : ""}>${escape(label(value))}</option>`).join("");
  replacePage(`<section class="characters-page real-character-page"><div class="page-title-row"><div><div class="eyebrow">GENSHIN IMPACT · CHARACTER DIRECTORY</div><h1>原神角色资料目录</h1><p>${coverage}</p></div><span id="real-character-count" class="tag tag-blue" role="status"></span></div>
    <div class="character-toolbar"><label>查找角色<input id="real-character-query" maxlength="160" placeholder="角色名、武器或地区" value="${escape(selection.query)}"></label><label>元素<select id="real-character-element" aria-label="元素"><option value="all">全部元素</option>${options(elements, selection.element, elementLabel)}</select></label><label>地区<select id="real-character-region" aria-label="地区"><option value="all">全部地区</option>${options(regions, selection.region)}<option value="missing" ${selection.region === "missing" ? "selected" : ""}>来源未提供</option></select></label><button id="real-character-reset" class="button">重置筛选</button></div>
    <div id="real-character-grid" class="character-grid"></div><div class="pagination" aria-label="角色目录分页"><button id="real-character-previous" class="button">上一页</button><span id="real-character-page"></span><button id="real-character-next" class="button">下一页</button></div>
    <div class="callout">${data.official_art?.status === "available" ? `已匹配 ${data.official_art.records.length} 组官网图片，图片由官方站点在线提供。` : "图片资料暂不可用。"}完整角色故事尚未收录，官方简介可通过官网入口查看。剧情检索和关系图仍使用原创样本。</div>${source}<a class="text-button" href="#/real-characters">打开最新目录 →</a> · <a class="text-button" href="#/characters">查看原创样本目录 →</a></section>`);
  function draw() {
    const result = catalogPage(data.characters, selection);
    selection.page = result.page;
    history.replaceState(null, "", catalogAddress(catalog, null, selection));
    document.querySelector("#real-character-count").textContent = `${result.total} / ${data.characters.length} 条角色记录`;
    document.querySelector("#real-character-grid").innerHTML = result.records.map((character) => {
      const official = officialReference(data, character);
      return `<article class="character-card"><a href="${catalogAddress(catalog, character.id, selection)}" aria-label="查看${escape(character.name)}详情">${portraitHTML(data, character)}</a><div class="character-card-body"><div class="eyebrow">${escape(valueLabel(character.region))} · ${character.rarity} 星</div><h2><a href="${catalogAddress(catalog, character.id, selection)}">${escape(character.name)}</a></h2>${facts(character, ["element", "weapon"])}<div class="real-character-actions"><a class="text-button" href="${catalogAddress(catalog, character.id, selection)}">基本资料与出处 →</a>${official ? officialButton(official, true) : `<span class="small muted">${data.official_links?.status === "available" ? "官网入口未匹配" : "官网入口暂不可用"}</span>`}</div></div></article>`;
    }).join("") || '<div class="empty-state">没有符合筛选条件的角色。</div>';
    document.querySelector("#real-character-page").textContent = `第 ${result.page} / ${result.pages} 页 · 每页最多 24 条`;
    document.querySelector("#real-character-previous").disabled = result.page === 1;
    document.querySelector("#real-character-next").disabled = result.page === result.pages;
    bindPortraits(document.querySelector('#real-character-grid'));
  }
  const input = document.querySelector("#real-character-query");
  const search = () => { selection.query = input.value; selection.page = 1; draw(); };
  input.addEventListener("input", (event) => { if (!event.isComposing) search(); });
  input.addEventListener("compositionend", search);
  for (const field of ["element", "region"]) document.querySelector(`#real-character-${field}`).addEventListener("change", (event) => { selection[field] = event.target.value; selection.page = 1; draw(); });
  document.querySelector("#real-character-reset").addEventListener("click", () => {
    Object.assign(selection, { query: "", element: "all", region: "all", page: 1 });
    input.value = "";
    for (const field of ["element", "region"]) document.querySelector(`#real-character-${field}`).value = "all";
    draw();
  });
  for (const [direction, step] of [["previous", -1], ["next", 1]]) document.querySelector(`#real-character-${direction}`).addEventListener("click", () => {
    selection.page += step; draw(); document.querySelector("#real-character-grid").scrollIntoView({ block: "start" });
  });
  draw();
}
