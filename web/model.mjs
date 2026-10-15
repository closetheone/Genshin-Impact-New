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

// Preview only: server-side material validation remains authoritative.
export function relationshipUsage(view, relation, purposes) {
  const sources = new Map((view.sources || []).map((item) => [item.id, item]));
  const characters = new Map(view.characters.map((item) => [item.id, item]));
  const entries = new Map(view.entries.map((item) => [item.id, item]));
  const passages = new Map(view.passages.map((item) => [item.id, item]));
  const combine = (states) => states.includes("denied") ? "denied" : states.includes("unknown") ? "unknown" : "allowed";
  const recordState = (record) => {
    const source = sources.get(record?.source_id);
    return combine(purposes.map((purpose) => {
      const right = source?.rights?.[purpose];
      return right === "allowed" || right === "denied" ? right : "unknown";
    }));
  };
  const base = combine([relation, characters.get(relation.from_id), characters.get(relation.to_id)].map(recordState));
  const groups = relation.evidence_groups.map((group) => combine([base, ...group.map((id) => {
    const passage = passages.get(id);
    return combine([recordState(passage), recordState(entries.get(passage?.entry_id)),
      passage && passage.speaker_id === null ? "allowed" : recordState(characters.get(passage?.speaker_id))]);
  }), ...(group.length ? [] : ["unknown"])]));
  const availableGroups = groups.filter((status) => status === "allowed").length;
  return { status: availableGroups ? "allowed" : groups.includes("unknown") || !groups.length ? "unknown" : "denied",
    availableGroups, totalGroups: groups.length, base };
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

export function safeLayout(saved, characters) {
  if (!saved || typeof saved !== "object" || !saved.positions || typeof saved.positions !== "object") return null;
  const positions = Object.create(null);
  for (const character of characters) {
    const point = saved.positions[character.id];
    if (Array.isArray(point) && point.length === 2 && point.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)) positions[character.id] = point;
  }
  return {
    positions,
    scale: Number.isFinite(saved.scale) && saved.scale >= .6 && saved.scale <= 1.8 ? saved.scale : 1,
    pan: Array.isArray(saved.pan) && saved.pan.length === 2 && saved.pan.every((value) => Number.isFinite(value) && Math.abs(value) <= 3) ? saved.pan : [0, 0],
  };
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
