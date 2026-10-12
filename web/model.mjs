export const SCOPES = {
  opening: ["opening"],
  east: ["opening", "east"],
  west: ["opening", "west"],
  all: ["opening", "east", "west", "later"],
};

export const PREDICATES = {
  mentor_of: { label: "师徒", color: "#8c9861" },
  parent_of: { label: "亲属", color: "#b69656" },
  opposes: { label: "对立", color: "#ac7867" },
  cooperates_with: { label: "合作", color: "#67998e" },
};

export const normalizeText = (value) => value.normalize("NFKC").replace(/\s+/gu, " ").trim();

export function searchPassages(passages, query) {
  const normalized = normalizeText(query);
  return passages.filter((passage) => normalizeText(passage.text).includes(normalized));
}

export function orderPassages(passages) {
  const byId = new Map(passages.map((passage) => [passage.id, passage]));
  const ranks = new Map(passages.map((passage, index) => [passage.id, index]));
  const incoming = new Map(passages.map((passage) => [passage.id, 0]));
  for (const passage of passages) {
    for (const nextId of passage.next_ids) {
      if (byId.has(nextId)) incoming.set(nextId, incoming.get(nextId) + 1);
    }
  }
  const ready = passages.filter((passage) => incoming.get(passage.id) === 0);
  const ordered = [];
  while (ready.length) {
    ready.sort((left, right) => ranks.get(left.id) - ranks.get(right.id));
    const passage = ready.shift();
    ordered.push(passage);
    for (const nextId of passage.next_ids) {
      if (!byId.has(nextId)) continue;
      incoming.set(nextId, incoming.get(nextId) - 1);
      if (incoming.get(nextId) === 0) ready.push(byId.get(nextId));
    }
  }
  if (ordered.length !== passages.length) throw new Error("样本对话存在循环，无法确定阅读顺序。");
  return ordered;
}

export function characterLabels(characters) {
  return new Map(characters.map((character) => {
    const duplicated = characters.filter((candidate) => candidate.name === character.name).length > 1;
    return [character.id, duplicated ? `${character.name} · ${character.id}` : character.name];
  }));
}

export function neighborhood(view, centerId, hops = 1, predicate = "all") {
  const candidates = view.relationships.filter((relation) => predicate === "all" || relation.predicate === predicate);
  const visible = new Set(view.characters.some((character) => character.id === centerId) ? [centerId] : []);
  for (let depth = 0; depth < Math.min(2, Math.max(1, hops)); depth += 1) {
    const frontier = new Set(visible);
    for (const relation of candidates) {
      if (frontier.has(relation.from_id)) visible.add(relation.to_id);
      if (frontier.has(relation.to_id)) visible.add(relation.from_id);
    }
  }
  const reached = view.characters.filter((character) => visible.has(character.id));
  reached.sort((left, right) => Number(right.id === centerId) - Number(left.id === centerId));
  const nodes = reached.slice(0, 50);
  const nodeIds = new Set(nodes.map((character) => character.id));
  const edges = candidates.filter((relation) => nodeIds.has(relation.from_id) && nodeIds.has(relation.to_id));
  return { nodes, edges: edges.slice(0, 100), truncated: reached.length > 50 || edges.length > 100 };
}

export function scopeLabel(record) {
  if (record.branch_id === "east") return "东路分支";
  if (record.branch_id === "west") return "西路分支";
  if (record.required_scope_ids.includes("later")) return "后续阶段";
  return "开篇 / 公共段落";
}

export function relationScope(relation, passages) {
  const byId = new Map(passages.map((passage) => [passage.id, passage]));
  const laterEvidence = relation.evidence_groups.some((group) => group.some((identifier) => byId.get(identifier)?.required_scope_ids.includes("later")));
  return `${scopeLabel(relation)}${laterEvidence ? " · 含后续证据" : ""}`;
}
