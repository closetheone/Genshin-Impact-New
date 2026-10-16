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
};

export const DEFAULT_CATALOG = "genshin-basics-2026-10-15-v2";

export function valueLabel(value: string | number | null | undefined) {
  return value === null || value === undefined || value === "" ? "来源未提供" : String(value);
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
