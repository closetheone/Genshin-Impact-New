from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from character_art import ART, official_art, validate_art
from character_catalog import BATCH, LEGACY_BATCH
from character_references import REFERENCES

DATA = json.loads(ART.read_text())
LINKS = json.loads(REFERENCES.read_text())
FULL = json.loads(BATCH.read_text())


class CharacterArtTests(unittest.TestCase):
    def test_coverage_and_catalog_identity(self):
        original = deepcopy(FULL)
        art = official_art(FULL)
        self.assertEqual(len(art['records']), 120)
        self.assertEqual(art['display_mode'], 'remote_reference')
        self.assertEqual(FULL, original)
        self.assertEqual(len(official_art(json.loads(LEGACY_BATCH.read_text()))['records']), 4)
        for name in ('神里绫华', '空'):
            character = next(c for c in FULL['characters'] if c['name'] == name)
            self.assertEqual(len(official_art({'character': character})['records']), 1 if name == '神里绫华' else 0)
            self.assertEqual(official_art({'character': {**character, 'name': '不匹配'}})['records'], [])

    def test_invalid_image_destinations_and_payloads_rejected(self):
        for url in ('javascript:alert(1)', 'https://uploadstatic.mihoyo.com.evil.test/contentweb/a.png',
                    'http://uploadstatic.mihoyo.com/contentweb/a.png', 'https://uploadstatic.mihoyo.com:443/contentweb/a.png',
                    'https://uploadstatic.mihoyo.com/contentweb/a.svg', 'https://uploadstatic.mihoyo.com/contentweb/../a.png',
                    'https://uploadstatic.mihoyo.com/contentweb/a.png?url=http://localhost/', 'data:image/png;base64,abc',
                    'https://127.0.0.1/contentweb/a.png'):
            for field in ('portrait_url', 'thumbnail_url'):
                data = deepcopy(DATA); data['records'][0][field] = url
                with self.subTest(url=url, field=field), self.assertRaises(ValueError): validate_art(data, LINKS)
        data = deepcopy(DATA); data['records'][0]['image_bytes'] = 'not permitted'
        with self.assertRaises(ValueError): validate_art(data, LINKS)

    def test_mismatched_source_or_duplicates_rejected(self):
        for field, value in [('character_id', 'genshin:00000000'), ('name', '其他角色'),
                             ('source_url', LINKS['records'][1]['url'])]:
            data = deepcopy(DATA); data['records'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_art(data, LINKS)
        data = deepcopy(DATA); data['records'].append(data['records'][0])
        with self.assertRaises(ValueError): validate_art(data, LINKS)
        data = deepcopy(DATA); data['reference_id'] = 'unreviewed'
        with self.assertRaises(ValueError): validate_art(data, LINKS)

    def test_invalid_supplement_falls_back_without_network_or_catalog_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'art.json'
            self.assertEqual(official_art(FULL, path), {'status': 'unavailable', 'records': []})
            for value in ('{}', 'null', 'invalid'):
                path.write_text(value)
                self.assertEqual(official_art(FULL, path), {'status': 'unavailable', 'records': []})
