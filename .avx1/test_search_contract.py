"""PR178 independent search fixes; synthetic files and fake RG, real HTTP route."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_terminal_mainstream import main, AUTH, FOLDER, TestClient, env_patch, fixture


class SearchContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=FOLDER)
        self.root = Path(self.directory.name)
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def matches(self, path, text, query, rg):
        path.write_text(text, encoding='utf-8', newline='')
        @contextmanager
        def matching(*args):
            yield rg
        with patch.object(main, 'search_entries', return_value=[(str(path), 'file')]), \
             patch.object(main, 'matching_files', matching):
            response = self.client.get('/files/matches', headers=AUTH,
                params={'path': str(self.root), 'query': query})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_original_unicode_position_and_utf16_column_in_both_search_paths(self):
        for text, expected in [('İx target', 4), ('😀İx target', 6), ('Before TARGET', 8)]:
            for rg in [None, lambda path: True]:
                with self.subTest(text=text, rg=rg is not None):
                    data = self.matches(self.root / 'file.txt', text, 'target', rg)
                    match = data['results'][0]['content_matches'][0]
                    self.assertEqual(match, {'line': 1, 'column': expected, 'text': text})

    def test_size_cap_applies_before_rg_predicate(self):
        rg = Mock(return_value=True)
        with patch.object(main, 'MAX_CONTENT_SEARCH_FILE_SIZE', 32):
            data = self.matches(self.root / 'file.txt', 'target' * 100, 'target', rg)
        self.assertEqual(data['results'], [])
        rg.assert_not_called()

    def test_long_matching_line_reuses_bounded_preview_without_losing_position(self):
        text = '界' * 20000 + 'target' + 'suffix'
        for rg in [None, lambda path: True]:
            with self.subTest(rg=rg is not None):
                data = self.matches(self.root / 'file.txt', text, 'target', rg)
                match = data['results'][0]['content_matches'][0]
                self.assertEqual(match['column'], 20001)
                self.assertTrue(match['excerpt_truncated'])
                self.assertIn('target', match['text'])
                self.assertIn('truncated', match['text'])
                self.assertLess(len(match['text'].encode('utf-8')), 1600)

    def test_large_file_still_matches_filename_without_content_scan(self):
        rg = Mock(return_value=True)
        with patch.object(main, 'MAX_CONTENT_SEARCH_FILE_SIZE', 32):
            data = self.matches(self.root / 'target.txt', 'target' * 100, 'target', rg)
        self.assertEqual(len(data['results']), 1)
        self.assertTrue(data['results'][0]['name_match'])
        self.assertEqual(data['results'][0]['content_matches'], [])
        rg.assert_not_called()


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        env_patch.stop()
        fixture.cleanup()
