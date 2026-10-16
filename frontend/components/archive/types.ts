export const DEFAULT_SNAPSHOT = "fixture-2026-10-10-v1";
export const ALL_SCOPES = ["opening", "east", "west", "later"] as const;
export type Scope = (typeof ALL_SCOPES)[number];
export type Purpose = "display" | "export" | "external_ai";

export type ArchiveCharacter = {
  id: string;
  name: string;
  required_scope_ids: string[];
  snapshot_id: string;
  source_id: string;
};

export type ArchiveEntry = {
  id: string;
  title: string;
  category: string;
  required_scope_ids: string[];
  snapshot_id: string;
  source_id: string;
};

export type Passage = {
  id: string;
  entry_id: string;
  text: string;
  speaker_id: string | null;
  branch_id: string | null;
  next_ids: string[];
  required_scope_ids: string[];
  snapshot_id: string;
  source_id: string;
  source_locator: string;
};

export type Pagination = {
  total: number;
  offset: number;
  limit: number;
  page?: number;
  pages?: number;
  next_cursor: string | null;
  previous_cursor: string | null;
};

export type SearchResult = Passage;

export type SearchView = {
  dataset_kind: "synthetic";
  notice: string;
  snapshot_id: string;
  scope_ids: string[];
  purpose: Purpose;
  query: { q: string; mode: "literal" | "keywords"; category: string; speaker: string; limit: number };
  results: SearchResult[];
  entries: ArchiveEntry[];
  characters: ArchiveCharacter[];
  stats: { passages: number; characters: number; relationships: number };
  facets: { categories: Array<{ value: string; count: number }>; speakers: Array<{ value: string; count: number }> };
  pagination: Pagination;
};

export type ReaderView = {
  dataset_kind: "synthetic";
  notice: string;
  snapshot_id: string;
  scope_ids: string[];
  purpose: Purpose;
  entries: ArchiveEntry[];
  characters: ArchiveCharacter[];
  passages: Passage[];
  target_id: string | null;
  pagination: Pagination;
};

export function normalizeScope(scope: string | null | undefined) {
  return scope && (scope === "all" || ALL_SCOPES.includes(scope as Scope)) ? scope : "all";
}

export function scopeIds(scope: string) {
  return scope === "all" ? [...ALL_SCOPES] : [scope];
}

export function archiveParams({ snapshot, scope, purpose = "display" }: { snapshot: string; scope: string; purpose?: Purpose }) {
  const params = new URLSearchParams({ snapshot, purpose });
  for (const item of scopeIds(scope)) params.append("scope", item);
  return params;
}

export function speakerName(characters: ArchiveCharacter[], speakerId: string | null) {
  if (!speakerId) return "叙述";
  return characters.find((character) => character.id === speakerId)?.name || speakerId;
}

export function scopeLabel(passage: Passage) {
  if (passage.branch_id) return `分支：${passage.branch_id}`;
  return passage.required_scope_ids.includes("opening") ? "开篇公共" : passage.required_scope_ids.join("、");
}
