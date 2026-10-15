"""A separate, immutable SQLite catalog for narrowly scoped real character facts."""
import argparse
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from validate_sample import require

ROOT = Path(__file__).resolve().parents[1]
LEGACY_BATCH = ROOT / 'data/characters/genshin-basics-v1.json'
BATCH = ROOT / 'data/characters/genshin-basics-v2.json'
BATCHES = (LEGACY_BATCH, BATCH)
DATABASE = ROOT / 'data/local/character-catalog.sqlite3'
DEFAULT_CATALOG = 'genshin-basics-2026-10-15-v2'
REPOSITORY = 'https://github.com/theBowja/genshin-db'
FIELDS = {'name': 'name', 'element': 'elementText', 'weapon': 'weaponText', 'rarity': 'rarity',
          'region': 'region', 'affiliation': 'affiliation', 'birthday': 'birthday', 'constellation': 'constellation'}


class CatalogUnavailable(Exception):
    pass


def validate_catalog(data):
    require(isinstance(data, dict), 'expected catalog object')
    expanded = data.get('schema_version') == 'character-catalog-2'
    require(set(data) == {'schema_version', 'dataset_kind', 'catalog_id', 'checked_on', 'source', 'characters'} | ({'coverage'} if expanded else set()), 'unexpected catalog fields')
    require(data['schema_version'] in ('character-catalog-1', 'character-catalog-2') and data['dataset_kind'] == 'real_character_facts', 'unsupported character catalog')
    require(isinstance(data['catalog_id'], str) and re.fullmatch(r'[a-z0-9-]{1,100}', data['catalog_id']), 'invalid catalog id')
    date.fromisoformat(data['checked_on'])
    source = data['source']
    require(isinstance(source, dict) and set(source) == {'name', 'repository', 'revision', 'license', 'license_url', 'license_file', 'license_sha256', 'scope'}, 'unexpected source fields')
    require(source['repository'] == REPOSITORY and source['license'] == 'MIT', 'unreviewed source')
    require(isinstance(source['revision'], str) and re.fullmatch(r'[0-9a-f]{40}', source['revision']), 'source revision must be pinned')
    prefix = f"{REPOSITORY}/blob/{source['revision']}/"
    require(source['license_url'] == prefix + 'LICENSE' and source['license_file'] == 'data/licenses/genshin-db-MIT.txt', 'invalid license reference')
    require(source['license_sha256'] == hashlib.sha256((ROOT / source['license_file']).read_bytes()).hexdigest(), 'license notice changed')
    require(all(isinstance(source[k], str) and 0 < len(source[k]) <= 500 for k in ('name', 'scope')), 'missing source scope')
    records = data['characters']
    require(isinstance(records, list) and 0 < len(records) <= 200, 'catalog requires 1–200 characters')
    ids, slugs = set(), set()
    for record in records:
        require(isinstance(record, dict) and set(record) == {'id', 'slug', 'provenance'} | set(FIELDS), 'only reviewed basic character fields accepted')
        require(isinstance(record['id'], str) and re.fullmatch(r'genshin:[0-9]{8}', record['id']), 'invalid character id')
        require(isinstance(record['slug'], str) and re.fullmatch(r'[a-z0-9-]{1,80}', record['slug']), 'invalid slug')
        require(record['id'] not in ids and record['slug'] not in slugs, 'duplicate character')
        ids.add(record['id']); slugs.add(record['slug'])
        require(type(record['rarity']) is int and record['rarity'] in (4, 5), 'invalid rarity')
        for field in FIELDS.keys() - {'rarity'}:
            if expanded and field in ('region', 'affiliation', 'birthday', 'constellation') and record[field] is None:
                continue
            require(isinstance(record[field], str) and 0 < len(record[field]) <= 80, f'invalid {field}')
        require(record['element'] in ('风', '岩', '雷', '草', '水', '火', '冰') or (expanded and record['element'] == '无'), 'invalid element')
        require(record['weapon'] in ('单手剑', '双手剑', '长柄武器', '法器', '弓'), 'invalid weapon')
        provenance = record['provenance']
        require(isinstance(provenance, dict) and set(provenance) == {'url', 'sha256', 'fields'} | ({'git_blob_sha1'} if expanded else set()), 'missing field provenance')
        require(provenance['url'] == prefix + f"src/data/ChineseSimplified/characters/{record['slug']}.json", 'source must use the pinned revision')
        require(isinstance(provenance['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', provenance['sha256']), 'missing source hash')
        require(provenance['fields'] == FIELDS, 'unexpected field mapping')
        if expanded:
            require(isinstance(provenance['git_blob_sha1'], str) and re.fullmatch(r'[0-9a-f]{40}', provenance['git_blob_sha1']), 'missing git blob identity')
    if expanded:
        coverage = data['coverage']
        require(isinstance(coverage, dict) and set(coverage) == {'directory', 'record_count', 'inventory_sha256'}, 'missing source coverage')
        require(coverage['directory'] == 'src/data/ChineseSimplified/characters' and type(coverage['record_count']) is int and coverage['record_count'] == len(records), 'source count mismatch')
        inventory = ''.join(f"{r['slug']}.json\t{r['provenance']['git_blob_sha1']}\n" for r in sorted(records, key=lambda item: item['slug']))
        require(coverage['inventory_sha256'] == hashlib.sha256(inventory.encode()).hexdigest(), 'source inventory mismatch')
    return data


def import_catalog(data, database=DATABASE):
    validate_catalog(data)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE IF NOT EXISTS catalogs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, payload TEXT NOT NULL)')
        existing = connection.execute('SELECT digest FROM catalogs WHERE id=?', (data['catalog_id'],)).fetchone()
        require(not existing or existing[0] == digest, 'catalog id already exists with different content; use a new catalog id')
        connection.execute('INSERT OR IGNORE INTO catalogs VALUES (?,?,?)', (data['catalog_id'], digest, payload))
    return {'catalog_id': data['catalog_id'], 'count': len(data['characters']), 'digest': digest}


def read_catalog(database=DATABASE, catalog=DEFAULT_CATALOG, character=None):
    with closing(sqlite3.connect(f'{Path(database).resolve().as_uri()}?mode=ro', uri=True)) as connection:
        row = connection.execute('SELECT digest,payload FROM catalogs WHERE id=?', (catalog,)).fetchone()
    if row is None:
        raise CatalogUnavailable('真实角色资料版本不存在，未自动切换版本。')
    require(hashlib.sha256(row[1].encode()).hexdigest() == row[0], 'catalog integrity check failed')
    data = validate_catalog(json.loads(row[1]))
    if character is not None:
        selected = next((item for item in data['characters'] if item['id'] == character), None)
        if selected is None:
            raise CatalogUnavailable('此版本中没有该真实角色。')
        return {**{k: v for k, v in data.items() if k != 'characters'}, 'character': selected}
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import reviewed basic character facts; never accepts story text or images.')
    parser.add_argument('batch', nargs='?', type=Path, default=BATCH)
    parser.add_argument('--database', type=Path, default=DATABASE)
    args = parser.parse_args()
    print(json.dumps(import_catalog(json.loads(args.batch.read_text()), args.database), ensure_ascii=False))
