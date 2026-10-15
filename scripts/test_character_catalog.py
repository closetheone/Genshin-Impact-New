from copy import deepcopy
from contextlib import closing
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from archive_store import ensure_synthetic_dataset
from character_catalog import BATCH, DEFAULT_CATALOG, CatalogUnavailable, import_catalog, read_catalog, validate_catalog
from serve_prototype import PrototypeHandler

DATA = json.loads(BATCH.read_text())


class CharacterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'character-catalog.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_import_roundtrip_and_real_identity(self):
        result = import_catalog(DATA, self.database)
        self.assertEqual(result['count'], 4)
        self.assertEqual(read_catalog(self.database), DATA)
        self.assertEqual({c['name'] for c in DATA['characters']}, {'安柏', '凯亚', '丽莎', '琴'})
        detail = read_catalog(self.database, character='genshin:10000021')
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
        self.assertEqual(read_catalog(self.database), DATA)
        with self.assertRaises(CatalogUnavailable): read_catalog(self.database, catalog='missing')
        with self.assertRaises(CatalogUnavailable): read_catalog(self.database, character='person:student')

    def test_corrupt_payload_rejected(self):
        import_catalog(DATA, self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE catalogs SET payload='{}'")
        with self.assertRaises(ValueError): read_catalog(self.database)

    def test_http_detail_errors_and_module(self):
        import_catalog(DATA, self.database)
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
            self.assertEqual(get('')[0], 200)
            for query in ('catalog=missing', 'character=person%3Astudent'):
                self.assertEqual(get(query)[0], 404)
            for query in ('character=', 'purpose=export', 'scope=all', 'catalog=a&catalog=b'):
                self.assertEqual(get(query)[0], 400)
            with urlopen(base + '/real-characters.mjs') as response:
                self.assertIn('javascript', response.headers['Content-Type'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
