const escape = (value) => String(value ?? "").replace(/[&<>"']/gu, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fields = { element: "元素", weapon: "武器", rarity: "稀有度", region: "地区", affiliation: "所属组织", birthday: "生日", constellation: "命之座" };
const facts = (character) => `<dl class="character-facts">${Object.entries(fields).map(([key, label]) => `<div><dt>${label}</dt><dd>${escape(character[key])}${key === "rarity" ? " 星" : ""}</dd></div>`).join("")}</dl>`;
const address = (catalog, id) => `#/real-${id ? "character" : "characters"}?${new URLSearchParams({ catalog, ...(id ? { id } : {}) })}`;

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

export function renderRealCharacters(data, detail, replacePage) {
  const catalog = data.catalog_id;
  const source = `<p class="small muted">数据整理：${escape(data.source.name)} · 核对日期：${escape(data.checked_on)}<br>资料批次：<code>${escape(catalog)}</code> · 来源版本：<code>${escape(data.source.revision.slice(0, 12))}</code></p>`;
  if (detail) {
    const character = data.character;
    replacePage(`<section class="character-detail-page real-character-page"><a class="text-button" href="${address(catalog)}">← 返回真实角色目录</a><div class="character-detail-hero"><div class="character-portrait large real-portrait" data-element="${escape(character.element)}"><span>${escape(character.name.slice(0, 1))}</span><small>文字占位 · 非角色立绘</small></div><div><div class="eyebrow">GENSHIN IMPACT · CHARACTER PROFILE</div><h1>${escape(character.name)}</h1><p>${escape(character.region)} · ${escape(character.affiliation)}</p><span class="tag tag-blue">真实角色基础资料</span>${facts(character)}</div></div><h2>角色故事与立绘</h2><p>本批次已接入基础资料，尚未收录角色故事、对白与立绘。当前没有已核验的人物关系记录。</p><h2>资料出处</h2>${source}<p><a class="button button-soft" href="${escape(character.provenance.url)}" target="_blank" rel="noopener noreferrer">查看此角色的来源记录 ↗</a> <a class="text-button" href="${escape(data.source.license_url)}" target="_blank" rel="noopener noreferrer">仓库许可说明 ↗</a></p><details class="real-provenance"><summary>字段定位与核对记录</summary><dl>${Object.entries(character.provenance.fields).map(([field, original]) => `<dt>${escape(fields[field] || "角色名")}</dt><dd><code>/${escape(original)}</code></dd>`).join("")}</dl><p>来源文件 SHA-256：<code>${escape(character.provenance.sha256)}</code></p></details><p class="small muted">${escape(data.source.scope)}</p></section>`);
    return;
  }
  let query = "", element = "all";
  function draw() {
    const characters = data.characters.filter((character) => (element === "all" || character.element === element) && `${character.name} ${character.region} ${character.affiliation} ${character.weapon} ${character.slug}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
    replacePage(`<section class="characters-page real-character-page"><div class="page-title-row"><div><div class="eyebrow">GENSHIN IMPACT · FIRST COLLECTION</div><h1>真实角色，开始收录。</h1><p>首批 ${data.characters.length} 名角色的基础资料，可以查看元素、武器、生日和出处。</p></div><span class="tag tag-blue">${characters.length} / ${data.characters.length} 名角色</span></div><div class="character-toolbar"><label>查找角色<input id="real-character-query" maxlength="160" placeholder="角色名、武器或地区" value="${escape(query)}"></label><label>元素<select id="real-character-element"><option value="all">全部元素</option>${[...new Set(data.characters.map((c) => c.element))].map((name) => `<option value="${escape(name)}" ${element === name ? "selected" : ""}>${escape(name)}</option>`).join("")}</select></label></div><div class="character-grid">${characters.map((character) => `<article class="character-card"><a href="${address(catalog, character.id)}" aria-label="查看${escape(character.name)}详情"><div class="character-portrait real-portrait" data-element="${escape(character.element)}"><span>${escape(character.name.slice(0, 1))}</span><small>文字占位 · 非角色立绘</small></div></a><div class="character-card-body"><div class="eyebrow">${escape(character.region)} · ${character.rarity} 星</div><h2><a href="${address(catalog, character.id)}">${escape(character.name)}</a></h2>${facts(character)}<a class="text-button" href="${address(catalog, character.id)}">基本资料与出处 →</a></div></article>`).join("") || '<div class="empty-state">没有符合筛选条件的角色。</div>'}</div><div class="callout">首批仅含角色基础资料，故事与立绘尚未收录。剧情检索和关系图仍使用原创样本。</div>${source}<a class="text-button" href="#/characters">查看原创样本目录 →</a></section>`);
    const input = document.querySelector("#real-character-query");
    input.addEventListener("input", (event) => {
      if (event.isComposing) return;
      query = event.target.value;
      const caret = event.target.selectionStart;
      draw();
      const next = document.querySelector("#real-character-query");
      next.focus(); next.setSelectionRange(caret, caret);
    });
    document.querySelector("#real-character-element").addEventListener("change", (event) => { element = event.target.value; draw(); });
  }
  draw();
}
