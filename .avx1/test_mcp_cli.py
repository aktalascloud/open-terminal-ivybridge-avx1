"""Exercise MCP CLI key resolution with the real env loader and a stub server."""
import builtins
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from click.testing import CliRunner
from open_terminal import cli, config


class McpCli(unittest.TestCase):
    def invoke(self, *, values=None, arguments=(), secret=False, missing_file=False):
        with tempfile.TemporaryDirectory(prefix='terminal-mcp-cli-') as directory:
            root = Path(directory)
            config_path = root / 'config.toml'
            config_path.write_text('api_key = "synthetic-config"\nhost = "127.0.0.1"\nport = 8123\n', encoding='utf-8')
            environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('OPEN_TERMINAL_')}
            environment.update(XDG_CONFIG_HOME=str(root / 'xdg'), XDG_STATE_HOME=str(root / 'state'))
            environment.update(values or {})
            if secret or missing_file:
                secret_path = root / 'key.txt'
                if secret:
                    secret_path.write_text('synthetic-file\n', encoding='utf-8')
                environment['OPEN_TERMINAL_API_KEY_FILE'] = str(secret_path)
            received = []
            original_import = builtins.__import__

            def import_module(name, *args, **kwargs):
                if name != 'open_terminal.mcp_server':
                    return original_import(name, *args, **kwargs)
                spec = importlib.util.spec_from_file_location('_review_terminal_env', SOURCE / 'open_terminal/env.py')
                env = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(env)
                server = types.SimpleNamespace(run=lambda **options: received.append({
                    'key': env.API_KEY,
                    'file_present': 'OPEN_TERMINAL_API_KEY_FILE' in os.environ,
                    'options': options,
                }))
                return types.SimpleNamespace(mcp=server)

            with patch.dict(os.environ, environment, clear=True), \
                 patch.object(config, '_SYSTEM_CONFIG_PATH', root / 'no-system-config.toml'), \
                 patch('builtins.__import__', side_effect=import_module):
                try:
                    result = CliRunner().invoke(cli.main, ['mcp', '--config', str(config_path), *arguments])
                    return result, received
                finally:
                    config._config = {}

    def test_existing_sources_and_explicit_override(self):
        cases = [
            ({}, 'synthetic-config', False),
            ({'values': {'OPEN_TERMINAL_API_KEY': 'synthetic-env'}}, 'synthetic-env', False),
            ({'secret': True}, 'synthetic-file', True),
            ({'arguments': ['--api-key', 'synthetic-cli']}, 'synthetic-cli', False),
            ({'values': {'OPEN_TERMINAL_API_KEY': 'synthetic-env'}, 'arguments': ['--api-key', 'synthetic-cli']}, 'synthetic-cli', False),
            ({'secret': True, 'arguments': ['--api-key', 'synthetic-cli']}, 'synthetic-cli', False),
            ({'values': {'OPEN_TERMINAL_API_KEY': 'synthetic-env'}, 'secret': True, 'arguments': ['--api-key', 'synthetic-cli']}, 'synthetic-cli', False),
            ({'missing_file': True, 'arguments': ['--api-key', 'synthetic-cli']}, 'synthetic-cli', False),
        ]
        for settings, key, file_present in cases:
            with self.subTest(settings=settings):
                result, received = self.invoke(**settings)
                self.assertEqual(result.exit_code, 0, repr(result.exception))
                self.assertEqual(received, [{'key': key, 'file_present': file_present, 'options': {'transport': 'stdio'}}])
                self.assertNotIn(key, result.output)

    def test_mutually_exclusive_and_unreadable_sources_fail_before_start(self):
        for settings in [
            {'secret': True, 'values': {'OPEN_TERMINAL_API_KEY': 'synthetic-env'}},
            {'secret': True, 'values': {'OPEN_TERMINAL_API_KEY': ''}},
            {'missing_file': True},
        ]:
            with self.subTest(settings=settings):
                result, received = self.invoke(**settings)
                self.assertNotEqual(result.exit_code, 0)
                self.assertEqual(received, [])

    def test_http_preserves_host_port_and_key(self):
        result, received = self.invoke(arguments=['--transport', 'streamable-http', '--host', '127.0.0.1', '--port', '8124', '--api-key', 'synthetic-cli'])
        self.assertEqual(result.exit_code, 0, repr(result.exception))
        self.assertEqual(received, [{'key': 'synthetic-cli', 'file_present': False, 'options': {'transport': 'streamable-http', 'host': '127.0.0.1', 'port': 8124}}])


if __name__ == '__main__':
    unittest.main()
