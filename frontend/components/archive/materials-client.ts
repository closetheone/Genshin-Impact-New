import type { MaterialSelection } from "./types";

export const MATERIALS_KEY = "story-archive-materials-v1";

export function readLocalSelection(): MaterialSelection {
  const raw = window.localStorage.getItem(MATERIALS_KEY);
  if (!raw) return { version: 1, snapshot: null, topic: "", passage_ids: [], relationships: [] };
  const value = JSON.parse(raw) as MaterialSelection;
  if (value.version !== 1 || (value.snapshot !== null && typeof value.snapshot !== "string") || typeof value.topic !== "string" || !Array.isArray(value.passage_ids) || !Array.isArray(value.relationships)) throw new Error("本地素材清单格式损坏，请到素材页清空后重建。");
  return value;
}

export function addPassageToLocalSelection(id: string, snapshot: string) {
  const selection = readLocalSelection();
  if (selection.snapshot && selection.snapshot !== snapshot) throw new Error("清单已固定到另一个快照，请先到素材页清空后再加入。");
  const next = { ...selection, snapshot, passage_ids: selection.passage_ids.includes(id) ? selection.passage_ids : [...selection.passage_ids, id] };
  window.localStorage.setItem(MATERIALS_KEY, JSON.stringify(next));
}

export function addRelationshipToLocalSelection(id: string, evidenceIds: string[], snapshot: string) {
  const selection = readLocalSelection();
  if (selection.snapshot && selection.snapshot !== snapshot) throw new Error("清单已固定到另一个快照，请先到素材页清空后再加入。");
  const existing = selection.relationships.find((item) => item.id === id);
  if (!existing) selection.relationships = [...selection.relationships, { id, evidence_ids: evidenceIds }];
  window.localStorage.setItem(MATERIALS_KEY, JSON.stringify({ ...selection, snapshot }));
}
