"""Behavior tests for the fork's child-environment and MCP fixes."""
import os
import subprocess
import sys
import types
import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch


class TerminalTests(unittest.TestCase):
    def test_child_cannot_read_inherited_terminal_credentials(self):
        from open_terminal.env import sanitized_environ
        environment = {**os.environ, "OPEN_TERMINAL_API_KEY": "synthetic-secret",
                       "open_terminal_private": "synthetic-secret", "KEEP_APPLICATION_SETTING": "kept"}
        with patch.dict(os.environ, environment, clear=True):
            child_env = sanitized_environ({"EXTRA_SETTING": "extra"})
        result = subprocess.run([sys.executable, "-c", "import os; assert not any(k.upper().startswith('OPEN_TERMINAL_') for k in os.environ); assert os.environ['KEEP_APPLICATION_SETTING']=='kept'; assert os.environ['EXTRA_SETTING']=='extra'"],
                                env=child_env, capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_stdio_passes_no_network_arguments(self):
        from click.testing import CliRunner
        from open_terminal.cli import main
        received = []
        fake = types.ModuleType("open_terminal.mcp_server")
        fake.mcp = types.SimpleNamespace(run=lambda **kwargs: received.append(kwargs))
        with patch.dict(sys.modules, {"open_terminal.mcp_server": fake}), patch("open_terminal.config.init", return_value={}):
            result = CliRunner().invoke(main, ["mcp", "--transport", "stdio"])
        self.assertEqual(result.exit_code, 0, repr(result.exception))
        self.assertEqual(received, [{"transport": "stdio"}])


class SearchContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A fresh service instance uses only a synthetic credential and temporary files.
        os.environ['OPEN_TERMINAL_API_KEY']='synthetic-context-test'
        import importlib
        import open_terminal.env
        importlib.reload(open_terminal.env)
        from open_terminal.main import app
        from fastapi.testclient import TestClient
        cls.client=TestClient(app)
        cls.headers={'Authorization':'Bearer synthetic-context-test'}

    def test_megabyte_match_stays_discoverable_and_cannot_flood_context(self):
        with tempfile.TemporaryDirectory(prefix='terminal-context-') as folder:
            path=Path(folder)/'data.json';line='a'*1000000+'needle'+'b'*1000000
            path.write_text(line+'\n',encoding='utf-8')
            response=self.client.get('/files/grep',params={'query':'needle','path':str(path)},headers=self.headers)
            self.assertEqual(response.status_code,200,response.text[:200])
            matches=response.json()['matches'];self.assertEqual(len(matches),1)
            preview=matches[0]['content'];self.assertIn('needle',preview);self.assertIn('truncated',preview)
            self.assertLess(len(preview),400);self.assertEqual(matches[0]['line'],1)
            measurement={'input_chars':len(line),'preview_chars':len(preview),
                'reduction_percent':100*(1-len(preview)/len(line)),
                'scope':'Synthetic single-line grep preview content only; not runtime speed or LLM throughput'}
            root=Path(__file__).resolve().parents[1];out=root/'.avx1-work/grep-preview-measurement.json';out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(measurement),encoding='utf-8')

    def test_refactored_search_preserves_short_results_and_authentication(self):
        with tempfile.TemporaryDirectory(prefix='terminal-context-') as folder:
            path=Path(folder)/'source.txt';path.write_text('hello needle\n',encoding='utf-8')
            params={'query':'needle','path':str(path)}
            self.assertEqual(self.client.get('/files/grep',params=params).status_code,401)
            response=self.client.get('/files/grep',params=params,headers=self.headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['matches'][0]['content'],'hello needle')


if __name__ == "__main__":
    unittest.main()
