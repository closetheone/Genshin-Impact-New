"""Validated, immutable character story text extracted from a pinned community data revision."""
from datetime import date
import json
from pathlib import Path
import re

from validate_sample import require

ROOT = Path(__file__).resolve().parents[1]
STORIES = ROOT / 'data/characters/genshin-character-stories-v1.json'
CATALOG = ROOT / 'data/characters/genshin-basics-v2.json'


def validate_stories(data, catalog=None):
    require(isinstance(data, dict) and set(data) == {'schema_version','story_id','checked_on','dataset_kind','source','coverage','records'}, 'unexpected story fields')
    require(data['schema_version'] == 'character-stories-1' and data['dataset_kind'] == 'real_character_story_text', 'unsupported story schema')
    require(isinstance(data['story_id'], str) and re.fullmatch(r'[a-z0-9-]{1,100}', data['story_id']), 'invalid story id')
    date.fromisoformat(data['checked_on'])
    source = data['source']
    require(isinstance(source, dict) and set(source) == {'name','repository','revision','files','scope','license_note'}, 'invalid story source')
    require(source['repository'] == 'https://github.com/Sycamore0/GenshinData' and re.fullmatch(r'[0-9a-f]{40}', source['revision']), 'story source is not pinned')
    require(source['files'] == {'stories':'ExcelBinOutput/FetterStoryExcelConfigData.json','textmap':'TextMap/TextMapCHS.json'}, 'unexpected story source files')
    coverage = data['coverage']; require(isinstance(coverage, dict) and set(coverage) == {'record_count','characters_with_story','chapter_count'}, 'invalid story coverage')
    records = data['records']; require(isinstance(records, list) and len(records) == coverage['record_count'] and len(records) <= 200, 'invalid story records')
    catalog_data = catalog or json.loads(CATALOG.read_text())
    catalog_records = [catalog_data['character']] if 'character' in catalog_data else catalog_data['characters']
    identities = {(c['id'], c['name']) for c in catalog_records}
    seen = set(); chapters = 0; with_story = 0
    for record in records:
        require(isinstance(record, dict) and set(record) == {'character_id','name','chapters'}, 'invalid story record')
        identity = (record['character_id'], record['name']); require(identity in identities and identity not in seen, 'story identity mismatch or duplicate')
        seen.add(identity)
        rows = record['chapters']; require(isinstance(rows, list) and len(rows) <= 20, 'invalid story chapters')
        if rows: with_story += 1
        order = set()
        for chapter in rows:
            require(isinstance(chapter, dict) and set(chapter) == {'chapter','title','body','unlock_level'}, 'invalid story chapter')
            require(type(chapter['chapter']) is int and 1 <= chapter['chapter'] <= 20 and chapter['chapter'] not in order, 'invalid story chapter number')
            require(isinstance(chapter['title'], str) and 0 < len(chapter['title']) <= 200, 'invalid story title')
            require(isinstance(chapter['body'], str) and 0 < len(chapter['body']) <= 20000, 'invalid story body')
            require(chapter['unlock_level'] is None or type(chapter['unlock_level']) is int, 'invalid unlock level')
            order.add(chapter['chapter']); chapters += 1
    require(coverage['characters_with_story'] == with_story and coverage['chapter_count'] == chapters, 'story coverage mismatch')
    return data


def character_stories(catalog, path=STORIES):
    try:
        data = validate_stories(json.loads(Path(path).read_text()))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {'status':'unavailable','records':[]}
    identities = {(c['id'], c['name']) for c in ([catalog['character']] if 'character' in catalog else catalog['characters'])}
    return {'status':'available','story_id':data['story_id'],'checked_on':data['checked_on'],'source':data['source'],'coverage':data['coverage'],'records':[r for r in data['records'] if (r['character_id'],r['name']) in identities]}
