const escape = (value) => String(value ?? "").replace(/[&<>"']/gu, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fields = { element: "元素", weapon: "武器", rarity: "稀有度", region: "地区", affiliation: "所属组织", birthday: "生日", constellation: "命之座" };
const valueLabel = (value) => value === null || value === "" || value === undefined ? "来源未提供" : String(value);
const elementLabel = (value) => value === "无" ? "无固定元素（来源标注）" : value;
const facts = (character, keys = Object.keys(fields)) => `<dl class="character-facts">${keys.map((key) => `<div><dt>${fields[key]}</dt><dd>${escape(key === "element" ? elementLabel(character[key]) : valueLabel(character[key]))}${key === "rarity" ? " 星" : ""}</dd></div>`).join("")}</dl>`;

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
      <div class="character-detail-hero"><div class="character-portrait large real-portrait" data-element="${escape(character.element)}"><span>${escape(character.name.slice(0, 1))}</span><small>文字占位 · 非角色立绘</small></div><div><div class="eyebrow">GENSHIN IMPACT · CHARACTER PROFILE</div><h1>${escape(character.name)}</h1><p>${escape(valueLabel(character.region))} · ${escape(valueLabel(character.affiliation))}</p><span class="tag tag-blue">角色基础资料 · 社区来源</span>${facts(character)}</div></div>
      <h2>角色故事与立绘</h2><p>本批次已接入基础资料，尚未收录角色故事、对白与立绘。当前没有已核验的人物关系记录。</p>
      <h2>资料出处</h2>${source}<p class="small muted">${coverage} 未提供的字段不做推测补齐；“无”元素按来源保留，不展开成多个角色。</p><p><a class="button button-soft" href="${escape(character.provenance.url)}" target="_blank" rel="noopener noreferrer">查看此角色的来源记录 ↗</a> <a class="text-button" href="${escape(data.source.license_url)}" target="_blank" rel="noopener noreferrer">仓库许可说明 ↗</a></p>
      <details class="real-provenance"><summary>字段定位与核对记录</summary><dl>${Object.entries(character.provenance.fields).map(([field, original]) => `<dt>${escape(fields[field] || "角色名")}</dt><dd><code>/${escape(original)}</code></dd>`).join("")}</dl><p>来源文件 SHA-256：<code>${escape(character.provenance.sha256)}</code></p></details><p class="small muted">${escape(data.source.scope)}</p></section>`);
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
    <div class="callout">仅含角色基础资料，故事与立绘尚未收录。剧情检索和关系图仍使用原创样本。</div>${source}<a class="text-button" href="#/real-characters">打开最新目录 →</a> · <a class="text-button" href="#/characters">查看原创样本目录 →</a></section>`);
  function draw() {
    const result = catalogPage(data.characters, selection);
    selection.page = result.page;
    history.replaceState(null, "", catalogAddress(catalog, null, selection));
    document.querySelector("#real-character-count").textContent = `${result.total} / ${data.characters.length} 条角色记录`;
    document.querySelector("#real-character-grid").innerHTML = result.records.map((character) => `<article class="character-card"><a href="${catalogAddress(catalog, character.id, selection)}" aria-label="查看${escape(character.name)}详情"><div class="character-portrait real-portrait" data-element="${escape(character.element)}"><span>${escape(character.name.slice(0, 1))}</span><small>文字占位 · 非角色立绘</small></div></a><div class="character-card-body"><div class="eyebrow">${escape(valueLabel(character.region))} · ${character.rarity} 星</div><h2><a href="${catalogAddress(catalog, character.id, selection)}">${escape(character.name)}</a></h2>${facts(character, ["element", "weapon"])}<a class="text-button" href="${catalogAddress(catalog, character.id, selection)}">基本资料与出处 →</a></div></article>`).join("") || '<div class="empty-state">没有符合筛选条件的角色。</div>';
    document.querySelector("#real-character-page").textContent = `第 ${result.page} / ${result.pages} 页 · 每页最多 24 条`;
    document.querySelector("#real-character-previous").disabled = result.page === 1;
    document.querySelector("#real-character-next").disabled = result.page === result.pages;
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
