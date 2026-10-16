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

export type Relationship = {
  id: string;
  from_id: string;
  to_id: string;
  predicate: "mentor_of" | "parent_of" | "opposes" | "cooperates_with" | string;
  direction: "directed" | "symmetric";
  branch_id: string | null;
  description: string;
  claim_kind: string;
  review_status: string;
  evidence_groups: string[][];
  required_scope_ids: string[];
  snapshot_id: string;
  source_id: string;
};

export type GraphView = {
  dataset_kind: "synthetic";
  notice: string;
  snapshot_id: string;
  scope_ids: string[];
  purpose: Purpose;
  characters: ArchiveCharacter[];
  entries: ArchiveEntry[];
  relationships: Relationship[];
  passages: Passage[];
  query: { center: string; hops: number; predicate: string; condition: string; page: number };
  truncated: boolean;
  limits: { nodes: number; relationships: number };
  pagination: { page: number; pages: number; total_nodes: number; total_relationships: number; next_cursor: string | null; previous_cursor: string | null };
};

export type RelationshipView = Omit<GraphView, "query" | "truncated" | "limits" | "pagination"> & { relationships: [Relationship] | Relationship[]; sources: Array<{ id: string; locator: string; content_type: string; rights: Record<string, string>; snapshot_id: string }> };

export type MaterialSelection = { version: 1; snapshot: string | null; topic: string; passage_ids: string[]; relationships: Array<{ id: string; evidence_ids: string[] }> };
export type MaterialResult = { valid: boolean; snapshot_id: string; count: number; limit: number; selection: MaterialSelection; errors: Array<{ kind: string; id: string; code: string }>; preview: { passages: Passage[]; relationships: Relationship[] }; markdown: string | null; package: Record<string, unknown> | null };
export type StatusView = { dataset_kind: "synthetic"; notice: string; snapshot_id: string; scope_ids: string[]; purpose: Purpose; source_admission?: { ready: boolean; sources: Array<{ source_id: string; page_count: number; requested_uses: string[]; ready: boolean; missing_requirements: string[]; unapproved_uses: string[]; next_actions: string[] }> }; storage: string };

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

export const predicateLabels: Record<string, string> = {
  mentor_of: "师徒",
  parent_of: "亲属",
  opposes: "对立",
  cooperates_with: "合作",
};

export function relationScope(relation: Relationship) {
  if (relation.branch_id === "east") return "东路分支";
  if (relation.branch_id === "west") return "西路分支";
  return relation.required_scope_ids.includes("later") ? "后续阶段" : "开篇公共";
}
