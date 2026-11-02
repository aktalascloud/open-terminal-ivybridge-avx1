"""Git trust boundaries; synthetic identities/processes and one stdlib worker."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_terminal.utils.git import GitRepository, git_environment
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


class GitContracts(unittest.IsolatedAsyncioTestCase):
    def test_multiuser_credentials_and_agents_are_not_inherited(self):
        environment = {'OPEN_TERMINAL_API_KEY': 'synthetic-service', 'GH_TOKEN': 'synthetic-server',
            'GH_ENTERPRISE_TOKEN': 'synthetic-enterprise', 'GH_CONFIG_DIR': 'server-config',
            'SSH_AUTH_SOCK': 'server-socket', 'SSH_AGENT_PID': 'server-agent', 'GNUPGHOME': 'server-gpg',
            'GPG_AGENT_INFO': 'server-info', 'XDG_CONFIG_HOME': 'server-config', 'XDG_RUNTIME_DIR': 'server-runtime',
            'GIT_CONFIG_GLOBAL': 'server-git', 'git_config_system': 'server-git-lower', 'KEEP': 'preserved'}
        with patch.dict(os.environ, environment, clear=True):
            result = git_environment(NS(username='actor', home='actor-home'))
        for key in ['OPEN_TERMINAL_API_KEY', 'GH_TOKEN', 'GH_ENTERPRISE_TOKEN', 'SSH_AUTH_SOCK',
                    'SSH_AGENT_PID', 'GPG_AGENT_INFO', 'XDG_RUNTIME_DIR', 'GIT_CONFIG_GLOBAL', 'git_config_system']:
            self.assertNotIn(key, result)
        self.assertEqual(result['HOME'], 'actor-home')
        self.assertEqual(result['GH_CONFIG_DIR'], os.path.join('actor-home', '.config', 'gh'))
        self.assertEqual(result['GNUPGHOME'], os.path.join('actor-home', '.gnupg'))
        self.assertEqual(result['KEEP'], 'preserved')
        self.assertEqual(result['GH_PROMPT_DISABLED'], '1')

    def test_singleuser_signed_in_cli_identity_and_application_environment_are_preserved(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'synthetic-own', 'SSH_AUTH_SOCK': 'own-socket', 'KEEP': 'yes'}, clear=True):
            result = git_environment(NS(username=None, home='own-home'))
        self.assertEqual(result['GH_TOKEN'], 'synthetic-own')
        self.assertEqual(result['SSH_AUTH_SOCK'], 'own-socket')
        self.assertEqual(result['KEEP'], 'yes')

    def test_parent_and_absolute_file_paths_are_rejected_before_git(self):
        repo = GitRepository.__new__(GitRepository)
        repo.root = os.path.abspath('synthetic-repo')
        repo.fs = NS(_check_path=lambda path: None)
        for path in ['../outside', os.path.abspath('elsewhere')]:
            with self.subTest(path=path), self.assertRaises(HTTPException) as error:
                repo.file_path(path)
            self.assertEqual(error.exception.status_code, 400)

    def test_metadata_realpath_is_checked_under_the_actor_boundary(self):
        def check(path):
            if path == 'other-actor':
                raise PermissionError('synthetic boundary')
        repo = GitRepository.__new__(GitRepository)
        repo.fs = NS(_check_path=check)
        with patch('open_terminal.utils.git.os.path.realpath', return_value='other-actor'):
            with self.assertRaises(HTTPException) as error:
                repo.checked_path('own-looking-symlink')
        self.assertEqual(error.exception.status_code, 403)

    async def test_executable_is_resolved_before_repository_cwd_and_no_shell_is_used(self):
        repo = GitRepository.__new__(GitRepository)
        repo.root = os.path.abspath('synthetic-repo')
        repo.fs = NS(username=None, home='synthetic-home')
        class Stream:
            async def read(self, size=-1): return b''
        process = NS(pid=123, returncode=0, stdout=Stream(), stderr=Stream(), wait=AsyncMock(return_value=0))
        resolved = os.path.abspath('trusted-tools/git.exe')
        with patch('open_terminal.utils.git.shutil.which', return_value=resolved), \
             patch('open_terminal.utils.git.asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)) as launch, \
             patch('open_terminal.utils.git.os.name', 'nt'):
            self.assertEqual(await repo.run('status', '--porcelain'), (0, '', ''))
        self.assertEqual(launch.call_args.args[0], resolved)
        self.assertEqual(launch.call_args.kwargs['cwd'], repo.root)
        self.assertNotIn('shell', launch.call_args.kwargs)

    def test_stdlib_worker_ignores_repository_packages_and_pythonpath(self):
        work = ROOT / '.avx1-work'
        work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work, prefix='git-worker-') as directory:
            folder = Path(directory).resolve()
            self.assertTrue(folder.is_relative_to(work.resolve()))
            (folder / 'json.py').write_text("raise RuntimeError('repository json imported')", encoding='utf-8')
            (folder / 'open_terminal').mkdir()
            (folder / 'open_terminal/__init__.py').write_text("raise RuntimeError('repository package imported')", encoding='utf-8')
            (folder / 'text.txt').write_text('first\nsecond', encoding='utf-8')
            (folder / 'binary.bin').write_bytes(b'\x00binary')
            result = subprocess.run([sys.executable, '-I', str(ROOT / 'open_terminal/utils/git_line_stats.py')],
                input=json.dumps(['text.txt', 'binary.bin']).encode(), cwd=folder, capture_output=True, timeout=10,
                env={**{key: os.environ[key] for key in ['SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'TEMP', 'TMP'] if key in os.environ},
                     'PYTHONPATH': str(folder)},
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertEqual(json.loads(result.stdout), {'text.txt': 2, 'binary.bin': None})


if __name__ == '__main__':
    unittest.main()
