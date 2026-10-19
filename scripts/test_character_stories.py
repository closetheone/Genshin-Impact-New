from copy import deepcopy
import json
import tempfile
import unittest
from pathlib import Path

from character_stories import STORIES, character_stories, validate_stories

DATA = json.loads(STORIES.read_text())

class CharacterStoryTests(unittest.TestCase):
    def test_pinned_coverage_and_character_identity(self):
        checked = validate_stories(DATA)
        self.assertEqual(checked['coverage'], {'record_count': 124, 'characters_with_story': 69, 'chapter_count': 550})
        ayaka = {'character': {'id': 'genshin:10000002', 'name': '神里绫华'}}
        result = character_stories(ayaka)
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(len(result['records'][0]['chapters']), 8)

    def test_invalid_story_text_or_identity_is_rejected(self):
        changed = deepcopy(DATA)
        changed['records'][0]['chapters'][0]['body'] = ''
        with self.assertRaises(ValueError): validate_stories(changed)
        changed = deepcopy(DATA)
        changed['records'][0]['name'] = '其他角色'
        with self.assertRaises(ValueError): validate_stories(changed)

    def test_corrupt_supplement_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stories.json'
            path.write_text('{}')
            self.assertEqual(character_stories({'character': {'id': 'genshin:10000002', 'name': '神里绫华'}}, path), {'status': 'unavailable', 'records': []})
