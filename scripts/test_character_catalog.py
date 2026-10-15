from copy import deepcopy
from contextlib import closing
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import hashlib
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from archive_store import ensure_synthetic_dataset
from character_catalog import BATCH, LEGACY_BATCH, DEFAULT_CATALOG, CatalogUnavailable, import_catalog, read_catalog, validate_catalog
from serve_prototype import PrototypeHandler
from build_character_catalog import extract_record

DATA = json.loads(LEGACY_BATCH.read_text())
FULL = json.loads(BATCH.read_text())


class CharacterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'character-catalog.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_import_roundtrip_and_real_identity(self):
        result = import_catalog(DATA, self.database)
        self.assertEqual(result['count'], 4)
        self.assertEqual(read_catalog(self.database, catalog=DATA['catalog_id']), DATA)
        self.assertEqual({c['name'] for c in DATA['characters']}, {'安柏', '凯亚', '丽莎', '琴'})
        detail = read_catalog(self.database, catalog=DATA['catalog_id'], character='genshin:10000021')
        self.assertEqual(detail['character']['name'], '安柏')
        self.assertEqual(detail['character']['element'], '火')
        self.assertNotIn('characters', detail)
        with self.assertRaises(ValueError):
            ensure_synthetic_dataset(DATA)

    def test_no_story_image_or_unknown_fields_can_enter(self):
        for field in ('story', 'description', 'image', 'relationships', 'text'):
            data = deepcopy(DATA)
            data['characters'][0][field] = 'not permitted'
            with self.subTest(field=field), self.assertRaises(ValueError):
                import_catalog(data, self.database)
        self.assertFalse(self.database.exists())

    def test_provenance_must_be_pinned_and_license_retained(self):
        for change in ('url', 'hash', 'license', 'mapping', 'revision'):
            data = deepcopy(DATA)
            if change == 'url': data['characters'][0]['provenance']['url'] = 'javascript:alert(1)'
            if change == 'hash': data['characters'][0]['provenance']['sha256'] = ''
            if change == 'license': data['source']['license_sha256'] = '0' * 64
            if change == 'mapping': data['characters'][0]['provenance']['fields']['story'] = 'description'
            if change == 'revision': data['source']['revision'] = 'main'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_catalog(data)

    def test_immutable_version_and_missing_ids(self):
        import_catalog(DATA, self.database)
        import_catalog(DATA, self.database)
        changed = deepcopy(DATA)
        changed['characters'][0]['name'] = '改名'
        with self.assertRaises(ValueError): import_catalog(changed, self.database)
        self.assertEqual(read_catalog(self.database, catalog=DATA['catalog_id']), DATA)
        with self.assertRaises(CatalogUnavailable): read_catalog(self.database, catalog='missing')
        with self.assertRaises(CatalogUnavailable): read_catalog(self.database, catalog=DATA['catalog_id'], character='person:student')

    def test_corrupt_payload_rejected(self):
        import_catalog(DATA, self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE catalogs SET payload='{}'")
        with self.assertRaises(ValueError): read_catalog(self.database, catalog=DATA['catalog_id'])

    def test_full_catalog_keeps_legacy_and_special_records(self):
        import_catalog(DATA, self.database)
        import_catalog(FULL, self.database)
        self.assertEqual(len(read_catalog(self.database)['characters']), 124)
        self.assertEqual(read_catalog(self.database, catalog=DATA['catalog_id']), DATA)
        traveler = read_catalog(self.database, character='genshin:10000005')['character']
        self.assertEqual(traveler['element'], '无')
        self.assertIsNone(traveler['birthday'])
        self.assertIsNone(traveler['region'])
        self.assertEqual(len({c['id'] for c in FULL['characters']}), 124)

    def test_coverage_rejects_missing_or_modified_record(self):
        for change in ('remove', 'blob', 'duplicate'):
            data = deepcopy(FULL)
            if change == 'remove': data['characters'].pop()
            if change == 'blob': data['characters'][0]['provenance']['git_blob_sha1'] = '0' * 40
            if change == 'duplicate': data['characters'][-1] = data['characters'][0]
            with self.subTest(change=change), self.assertRaises(ValueError): validate_catalog(data)

    def test_required_identity_fields_never_become_nullable(self):
        for field in ('name', 'element', 'weapon', 'rarity'):
            data = deepcopy(FULL)
            data['characters'][0][field] = None
            with self.subTest(field=field), self.assertRaises(ValueError): validate_catalog(data)

    def test_extraction_verifies_blob_and_discards_prose(self):
        raw = json.dumps({'id': 10000005, 'name': '空', 'description': 'Must not be copied', 'region': '',
                          'elementText': '无', 'weaponText': '单手剑', 'rarity': 5, 'constellation': '旅人座'}).encode()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        record = extract_record(raw, 'src/data/ChineseSimplified/characters/aether.json', blob, FULL['source']['revision'])
        self.assertNotIn('description', record)
        self.assertIsNone(record['region'])
        self.assertIsNone(record['birthday'])
        with self.assertRaises(ValueError): extract_record(raw + b' ', 'aether.json', blob, FULL['source']['revision'])

    def test_http_detail_errors_and_module(self):
        import_catalog(DATA, self.database)
        import_catalog(FULL, self.database)
        server = ThreadingHTTPServer(('127.0.0.1', 0), PrototypeHandler)
        server.database = Path(self.temp.name) / 'archive.sqlite3'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def get(query):
            try: response = urlopen(base + '/api/character-catalog?' + query)
            except HTTPError as error: response = error
            with response:
                return response.status, json.load(response)
        try:
            status, data = get(urlencode({'catalog': DEFAULT_CATALOG, 'character': 'genshin:10000003'}))
            self.assertEqual(status, 200)
            self.assertEqual(data['character']['name'], '琴')
            self.assertEqual(len(get('')[1]['characters']), 124)
            self.assertEqual(len(get(urlencode({'catalog': DATA['catalog_id']}))[1]['characters']), 4)
            for query in ('catalog=missing', 'character=person%3Astudent'):
                self.assertEqual(get(query)[0], 404)
            for query in ('character=', 'purpose=export', 'scope=all', 'catalog=a&catalog=b'):
                self.assertEqual(get(query)[0], 400)
            with urlopen(base + '/real-characters.mjs') as response:
                self.assertIn('javascript', response.headers['Content-Type'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
