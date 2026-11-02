"""Isolated CLI CORS regressions; no server or host config is accessed."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

source = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(source))
from click.testing import CliRunner
from open_terminal import cli, config


class CorsPrecedence(unittest.TestCase):
    def invoke(self, *, system=None, user=None, environment=None, arguments=()):
        with tempfile.TemporaryDirectory(prefix='terminal-cors-review-') as directory:
            root = Path(directory)
            system_path = root / 'system.toml'
            user_path = root / 'xdg/open-terminal/config.toml'
            user_path.parent.mkdir(parents=True)
            for path, value in ((system_path, system), (user_path, user)):
                if value is not None:
                    path.write_text('cors_allowed_origins = ' + value + '\n', encoding='utf-8')
            environment_values = {k: v for k, v in os.environ.items() if not k.upper().startswith('OPEN_TERMINAL_')}
            environment_values.update(XDG_CONFIG_HOME=str(root / 'xdg'))
            environment_values.update(environment or {})
            received = []
            fake_env = types.ModuleType('open_terminal.env')
            fake_env.UVICORN_LOOP = 'auto'
            fake_env.UVICORN_TIMEOUT_KEEP_ALIVE = None
            with patch.dict(os.environ, environment_values, clear=True), \
                 patch.object(config, '_SYSTEM_CONFIG_PATH', system_path), \
                 patch.dict(sys.modules, {'open_terminal.env': fake_env}), \
                 patch.object(cli.uvicorn, 'run', side_effect=lambda *a, **k: received.append(os.environ.get('OPEN_TERMINAL_CORS_ALLOWED_ORIGINS'))):
                try:
                    result = CliRunner().invoke(cli.main, ['run', '--host', '127.0.0.1', '--api-key', 'synthetic-cors-review', *arguments])
                    return result, received
                finally:
                    config._config = {}

    def test_precedence_and_explicit_restrictions(self):
        cases = [
            ({}, '*'),
            ({'system': '"https://system.example"'}, 'https://system.example'),
            ({'system': '"https://system.example"', 'user': '"https://user.example"'}, 'https://user.example'),
            ({'user': '"https://user.example"', 'environment': {'OPEN_TERMINAL_CORS_ALLOWED_ORIGINS': 'https://env.example'}}, 'https://env.example'),
            ({'user': '"https://user.example"', 'arguments': ['--cors-allowed-origins', '*']}, '*'),
            ({'user': '"https://user.example"', 'arguments': ['--cors-allowed-origins', '']}, ''),
            ({'user': '"https://user.example"', 'environment': {'OPEN_TERMINAL_CORS_ALLOWED_ORIGINS': 'https://env.example'}, 'arguments': ['--cors-allowed-origins', 'https://cli.example']}, 'https://cli.example'),
            ({'user': '""'}, ''),
            ({'user': '"*"'}, '*'),
        ]
        for settings, expected in cases:
            with self.subTest(settings=settings):
                result, received = self.invoke(**settings)
                self.assertEqual(result.exit_code, 0, repr(result.exception))
                self.assertEqual(received, [expected])
                self.assertEqual("CORS is set to '*'" in result.output, expected == '*')

    def test_invalid_config_cannot_start_server(self):
        for value in ('123', 'true', '["https://list.example"]'):
            with self.subTest(value=value):
                result, received = self.invoke(user=value)
                self.assertEqual(result.exit_code, 2)
                self.assertEqual(received, [])
                self.assertIn('cors_allowed_origins', result.output)


if __name__ == '__main__':
    unittest.main()
