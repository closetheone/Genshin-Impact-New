export type Character = {
  id: string;
  slug: string;
  name: string;
  element: string;
  weapon: string;
  rarity: number;
  region: string | null;
  affiliation: string | null;
  birthday: string | null;
  constellation: string | null;
  provenance: {
    url: string;
    fields: Record<string, string>;
    sha256: string;
  };
};

export type OfficialArt = {
  character_id: string;
  name: string;
  source_url: string;
  portrait_url: string;
  thumbnail_url: string;
};

export type OfficialLink = {
  character_id: string;
  name: string;
  section: string;
  url: string;
};

export type StoryChapter = {
  chapter: number;
  title: string;
  body: string;
  unlock_level: number | null;
};

export type CharacterStory = {
  character_id: string;
  name: string;
  chapters: StoryChapter[];
};

export type Catalog = {
  catalog_id: string;
  checked_on: string;
  dataset_kind: string;
  characters: Character[];
  coverage?: { record_count: number };
  source: {
    name: string;
    repository: string;
    revision: string;
    license_url: string;
    scope: string;
  };
  official_art?: {
    status: string;
    copyright?: string;
    records: OfficialArt[];
  };
  official_links?: {
    status: string;
    records: OfficialLink[];
  };
  stories?: {
    status: string;
    story_id?: string;
    checked_on?: string;
    source?: { name: string; repository: string; revision: string; files: Record<string, string>; scope: string; license_note: string };
    coverage?: { record_count: number; characters_with_story: number; chapter_count: number };
    records: CharacterStory[];
  };
};

export const DEFAULT_CATALOG = "genshin-basics-2026-10-15-v2";

const completenessFields: Array<[keyof Character, string]> = [
  ["name", "名称"], ["element", "元素"], ["weapon", "武器"], ["rarity", "稀有度"],
  ["region", "地区"], ["affiliation", "所属组织"], ["birthday", "生日"], ["constellation", "命之座"],
];

export function valueLabel(value: string | number | null | undefined) {
  return value === null || value === undefined || value === "" ? "来源未提供" : String(value);
}

export function characterCompleteness(character: Character) {
  const missing = completenessFields
    .filter(([field]) => character[field] === null || character[field] === undefined || character[field] === "")
    .map(([, label]) => label);
  return { available: completenessFields.length - missing.length, total: completenessFields.length, missing };
}

export function findArt(catalog: Catalog, character: Character) {
  return catalog.official_art?.records.find(
    (record) => record.character_id === character.id && record.name === character.name,
  );
}

export function findOfficialLink(catalog: Catalog, character: Character) {
  return catalog.official_links?.records.find(
    (record) => record.character_id === character.id && record.name === character.name,
  );
}

export function findStory(catalog: Catalog, character: Character) {
  return catalog.stories?.records.find(
    (record) => record.character_id === character.id && record.name === character.name,
  );
}
