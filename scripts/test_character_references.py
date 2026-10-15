from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from character_catalog import BATCH, LEGACY_BATCH
from character_references import REFERENCES, official_links, validate_references

DATA = json.loads(REFERENCES.read_text())
FULL = json.loads(BATCH.read_text())


class CharacterReferenceTests(unittest.TestCase):
    def test_official_matches_and_unmatched_records(self):
        original = deepcopy(FULL)
        links = official_links(FULL)
        self.assertEqual(links['status'], 'available')
        self.assertEqual(len(links['records']), 120)
        matched = {r['character_id'] for r in links['records']}
        self.assertEqual({c['name'] for c in FULL['characters'] if c['id'] not in matched},
                         {'空', '荧', '奇偶·男性', '奇偶·女性'})
        self.assertEqual(FULL, original)
        self.assertEqual(len(official_links(json.loads(LEGACY_BATCH.read_text()))['records']), 4)

    def test_detail_matches_both_id_and_name(self):
        ayaka = next(c for c in FULL['characters'] if c['name'] == '神里绫华')
        links = official_links({'character': ayaka})['records']
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['url'], 'https://ys.mihoyo.com/main/character/inazuma?char=0')
        for character in ({**ayaka, 'name': '其他角色'}, {**ayaka, 'id': 'genshin:00000000'}):
            self.assertEqual(official_links({'character': character})['records'], [])

    def test_destinations_reject_scripts_lookalikes_and_unknown_parameters(self):
        for url in ('javascript:alert(1)', 'https://ys.mihoyo.com.evil.test/main/character/mondstadt?char=0',
                    'http://ys.mihoyo.com/main/character/mondstadt?char=0',
                    'https://ys.mihoyo.com/main/character/mondstadt?char=0&redirect=elsewhere',
                    'https://ys.mihoyo.com/main/character/mondstadt?char=-1',
                    'https://ys.mihoyo.com/main/character/mondstadt?char=200'):
            data = deepcopy(DATA)
            data['records'][0]['url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_references(data)

    def test_duplicate_identity_destination_and_content_are_rejected(self):
        for field in ('character_id', 'name', 'url'):
            data = deepcopy(DATA)
            data['records'][1][field] = data['records'][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_references(data)
        for field in ('story', 'image', 'description'):
            data = deepcopy(DATA)
            data['records'][0][field] = 'not navigation metadata'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_references(data)

    def test_missing_or_invalid_supplement_does_not_block_basic_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'references.json'
            self.assertEqual(official_links(FULL, path), {'status': 'unavailable', 'records': []})
            for content in ('invalid json', '{}', '{"schema_version":null}'):
                path.write_text(content)
                self.assertEqual(official_links(FULL, path), {'status': 'unavailable', 'records': []})
