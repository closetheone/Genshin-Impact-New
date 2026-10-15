"""Reviewed external navigation metadata; no artwork or story content."""
from datetime import date
import json
from pathlib import Path
import re

from validate_sample import require

REFERENCES = Path(__file__).resolve().parents[1] / 'data/characters/official-character-links-v1.json'
SECTIONS = {'mondstadt': '蒙德城', 'liyue': '璃月港', 'inazuma': '稻妻城',
            'sumeru': '须弥城', 'fontaine': '枫丹廷', 'natlan': '纳塔', 'snezhnaya': '至冬'}


def validate_references(data):
    require(isinstance(data, dict) and set(data) == {'schema_version', 'reference_id', 'checked_on', 'source_name', 'method', 'records'}, 'unexpected reference fields')
    require(data['schema_version'] == 'official-character-links-1', 'unsupported reference format')
    require(isinstance(data['reference_id'], str) and re.fullmatch(r'[a-z0-9-]{1,100}', data['reference_id']), 'invalid reference id')
    date.fromisoformat(data['checked_on'])
    require(data['source_name'] == '《原神》官方网站' and data['method'] == 'official_character_selector_exact_name', 'unreviewed reference source')
    require(isinstance(data['records'], list) and 0 < len(data['records']) <= 200, 'invalid reference count')
    ids, names, urls = set(), set(), set()
    for record in data['records']:
        require(isinstance(record, dict) and set(record) == {'character_id', 'name', 'section', 'url'}, 'only navigation metadata accepted')
        require(isinstance(record['character_id'], str) and re.fullmatch(r'genshin:[0-9]{8}', record['character_id']), 'invalid character id')
        require(isinstance(record['name'], str) and 0 < len(record['name']) <= 80, 'invalid character name')
        require(isinstance(record['url'], str), 'invalid official url')
        match = re.fullmatch(r'https://ys\.mihoyo\.com/main/character/([a-z]+)\?char=(0|[1-9][0-9]{0,2})', record['url'])
        require(match and match[1] in SECTIONS and int(match[2]) < 200, 'unexpected official destination')
        require(record['section'] == SECTIONS[match[1]], 'official section mismatch')
        require(record['character_id'] not in ids and record['name'] not in names and record['url'] not in urls, 'duplicate reference')
        ids.add(record['character_id']); names.add(record['name']); urls.add(record['url'])
    return data


def official_links(catalog, path=REFERENCES):
    """Join by both ID and name, keeping the immutable facts batch untouched.

    A missing or invalid supplement must not prevent reading basic facts.
    The external site may change its positional URLs after the review date.
    """
    try:
        data = validate_references(json.loads(Path(path).read_text()))
    except (OSError, ValueError, TypeError, KeyError):
        return {'status': 'unavailable', 'records': []}
    characters = [catalog['character']] if 'character' in catalog else catalog['characters']
    identities = {(c['id'], c['name']) for c in characters}
    records = [r for r in data['records'] if (r['character_id'], r['name']) in identities]
    return {'status': 'available', 'reference_id': data['reference_id'], 'checked_on': data['checked_on'],
            'source_name': data['source_name'], 'records': records}
