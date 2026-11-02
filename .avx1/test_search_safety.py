"""PR192 device/mount boundaries; synthetic stat data, no device is opened."""
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_terminal.utils import search


class SearchSafety(unittest.TestCase):
    def test_only_regular_files_are_content_candidates(self):
        for mode, expected in [(stat.S_IFREG, True), (stat.S_IFCHR, False), (stat.S_IFIFO, False), (stat.S_IFSOCK, False)]:
            with self.subTest(mode=mode), patch.object(search.os, 'stat', return_value=NS(st_mode=mode)):
                self.assertEqual(search.is_regular_file('synthetic-path'), expected)
        with patch.object(search.os, 'stat', side_effect=PermissionError):
            self.assertFalse(search.is_regular_file('unavailable'))

    def test_walk_does_not_cross_mounts_or_allowed_path_boundary(self):
        directories = ['same', 'mounted', 'forbidden']
        fs = NS(is_path_allowed=lambda path: os.path.basename(path) != 'forbidden')
        with patch.object(search.os, 'walk', return_value=[('root', directories, ['file.txt'])]), \
             patch.object(search, '_device', side_effect=lambda path: 2 if os.path.basename(path) == 'mounted' else 1):
            result = list(search.walk_entries(fs, 'root'))
        self.assertEqual({os.path.basename(path) for path, _ in result}, {'same', 'file.txt'})

    def test_explicit_mount_root_remains_searchable(self):
        directories = ['child']
        with patch.object(search.os, 'walk', return_value=[('mounted', directories, ['file.txt'])]), \
             patch.object(search, '_device', return_value=2):
            result = list(search.walk_entries(NS(is_path_allowed=lambda path: True), 'mounted'))
        self.assertEqual({os.path.basename(path) for path, _ in result}, {'child', 'file.txt'})

    def test_pseudo_filesystem_prefix_is_not_a_similar_directory_name(self):
        with patch.object(search.os.path, 'realpath', side_effect=lambda path: path), patch.object(search.os, 'sep', '/'):
            for root in ('/dev', '/dev/pts', '/proc/1', '/sys/kernel'):
                self.assertTrue(search._is_pseudo_filesystem(root))
            self.assertFalse(search._is_pseudo_filesystem('/devices'))

    def test_pseudo_root_never_reaches_ripgrep(self):
        with patch.object(search, '_is_pseudo_filesystem', return_value=True), patch.object(search.subprocess, 'run') as run:
            with search.matching_files('needle', '/dev', True) as matcher:
                self.assertIsNone(matcher)
            run.assert_not_called()

    def test_ripgrep_root_has_mount_and_pseudo_tree_guards(self):
        calls = []
        realpath = search.os.path.realpath
        temporary_directory = tempfile.TemporaryDirectory
        work = Path(__file__).resolve().parents[1] / '.avx1-work'
        work.mkdir(exist_ok=True)
        def owned_temporary(*args, **kwargs):
            kwargs['dir'] = work
            directory = temporary_directory(*args, **kwargs)
            assert Path(directory.name).resolve().is_relative_to(work.resolve())
            return directory
        def run(command, **kwargs):
            calls.append(command)
            return NS(returncode=0)
        with patch.object(search, '_is_pseudo_filesystem', return_value=False), \
             patch.object(search.os.path, 'realpath', side_effect=lambda path, **kwargs: os.path.sep if path == 'root' else realpath(path, **kwargs)), \
             patch.object(search.tempfile, 'TemporaryDirectory', side_effect=owned_temporary), \
             patch.object(search.shutil, 'which', return_value='synthetic-rg'), \
             patch.object(search.subprocess, 'run', side_effect=run):
            with search.matching_files('needle', 'root', False) as matcher:
                self.assertFalse(matcher('not-present'))
        self.assertIn('--one-file-system', calls[0])
        for glob in ('!dev/**', '!proc/**', '!sys/**'):
            self.assertIn(glob, calls[0])


if __name__ == '__main__':
    unittest.main()
