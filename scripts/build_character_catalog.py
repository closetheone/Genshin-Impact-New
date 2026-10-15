"""Build only basic facts from a pinned, complete Git character directory."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen

from character_catalog import FIELDS, LEGACY_BATCH, REPOSITORY, validate_catalog
from validate_sample import require

DIRECTORY = 'src/data/ChineseSimplified/characters'


def extract_record(raw, path, blob, revision):
    require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob, 'response differs from pinned git blob')
    upstream = json.loads(raw)
    facts = {field: upstream.get(original) for field, original in FIELDS.items()}
    for field in ('region', 'affiliation', 'birthday', 'constellation'):
        if facts[field] == '':
            facts[field] = None
    return {'id': f"genshin:{upstream['id']}", 'slug': Path(path).stem, **facts,
            'provenance': {'url': f'{REPOSITORY}/blob/{revision}/{path}',
                           'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob_sha1': blob, 'fields': FIELDS}}


def build(repository, revision, catalog_id, checked_on):
    require(bool(re.fullmatch(r'[0-9a-f]{40}', revision)), 'use a full pinned commit hash')
    tree = subprocess.check_output(['git', '-C', str(repository), 'ls-tree', '-r', revision, DIRECTORY], text=True)
    entries = []
    for line in tree.splitlines():
        metadata, path = line.split('\t')
        mode, kind, blob = metadata.split()
        require(mode == '100644' and kind == 'blob' and re.fullmatch(DIRECTORY + r'/[a-z0-9-]+\.json', path), 'unexpected character directory entry')
        entries.append((path, blob))
    require(bool(entries), 'character directory is empty')
    def fetch(entry):
        path, blob = entry
        with urlopen(f'https://raw.githubusercontent.com/theBowja/genshin-db/{revision}/{path}', timeout=30) as response:
            raw = response.read()
        return extract_record(raw, path, blob, revision)
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(fetch, entries))
    data = json.loads(LEGACY_BATCH.read_text())
    require(data['source']['revision'] == revision, 'new source revision requires a separate source/license review')
    inventory = ''.join(f"{r['slug']}.json\t{r['provenance']['git_blob_sha1']}\n" for r in sorted(records, key=lambda r: r['slug']))
    data.update(schema_version='character-catalog-2', catalog_id=catalog_id, checked_on=checked_on,
                characters=sorted(records, key=lambda r: r['id']),
                coverage={'directory': DIRECTORY, 'record_count': len(records), 'inventory_sha256': hashlib.sha256(inventory.encode()).hexdigest()})
    return validate_catalog(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--catalog-id', required=True)
    parser.add_argument('--checked-on', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = build(args.repository, args.revision, args.catalog_id, args.checked_on)
    # Never overwrite an existing batch, even before database import.
    with args.output.open('x') as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'catalog_id': data['catalog_id'], 'count': len(data['characters'])}))
