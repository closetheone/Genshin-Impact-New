"""Official-site image references for the local character viewer; no image proxy."""
from datetime import date
import json
from pathlib import Path
import re

from character_references import REFERENCES, validate_references
from validate_sample import require

ART = Path(__file__).resolve().parents[1] / 'data/characters/official-character-art-v1.json'
IMAGE_PATHS = {
    'https://uploadstatic.mihoyo.com': '/contentweb/',
    'https://webstatic.mihoyo.com': '/upload/contentweb/',
    'https://act-webstatic.mihoyo.com': '/upload/contentweb/',
    'https://fastcdn.mihoyo.com': '/content-v2/hk4e/',
}


def valid_image_url(url):
    return isinstance(url, str) and len(url) <= 500 and any(
        re.fullmatch(re.escape(origin + prefix) + r'[A-Za-z0-9/_-]+\.png', url)
        for origin, prefix in IMAGE_PATHS.items())


def validate_art(data, references):
    validate_references(references)
    require(isinstance(data, dict) and set(data) == {'schema_version', 'art_id', 'reference_id', 'checked_on', 'display_mode', 'copyright', 'records'}, 'unexpected art fields')
    require(data['schema_version'] == 'official-character-art-1' and data['display_mode'] == 'remote_reference', 'unsupported image display mode')
    require(isinstance(data['art_id'], str) and re.fullmatch(r'[a-z0-9-]{1,100}', data['art_id']), 'invalid art id')
    require(data['reference_id'] == references['reference_id'] and data['copyright'] == '© miHoYo', 'invalid image attribution')
    date.fromisoformat(data['checked_on'])
    require(isinstance(data['records'], list) and 0 < len(data['records']) <= 200, 'invalid image count')
    links = {r['character_id']: r for r in references['records']}
    seen = set()
    for record in data['records']:
        require(isinstance(record, dict) and set(record) == {'character_id', 'name', 'source_url', 'portrait_url', 'thumbnail_url'}, 'only image references accepted')
        require(isinstance(record['character_id'], str) and record['character_id'] in links, 'unknown image character')
        link = links[record['character_id']]
        require(record['name'] == link['name'] and record['source_url'] == link['url'], 'image source identity mismatch')
        require(record['character_id'] not in seen, 'duplicate character image')
        require(valid_image_url(record['portrait_url']) and valid_image_url(record['thumbnail_url']), 'unexpected image destination')
        seen.add(record['character_id'])
    return data


def official_art(catalog, path=ART, references_path=REFERENCES):
    try:
        data = validate_art(json.loads(Path(path).read_text()), json.loads(Path(references_path).read_text()))
    except (OSError, ValueError, TypeError, KeyError):
        return {'status': 'unavailable', 'records': []}
    characters = [catalog['character']] if 'character' in catalog else catalog['characters']
    identities = {(c['id'], c['name']) for c in characters}
    return {'status': 'available', 'art_id': data['art_id'], 'checked_on': data['checked_on'],
            'copyright': data['copyright'], 'display_mode': data['display_mode'],
            'records': [r for r in data['records'] if (r['character_id'], r['name']) in identities]}
