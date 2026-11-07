"""The default model catalog must not start or modify the owner's Cline profile."""
import ast
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException


class ClineDiscoveryPolicy(unittest.IsolatedAsyncioTestCase):
    def test_other_os_user_does_not_inherit_server_git_or_provider_credentials(self):
        root=Path(__file__).resolve().parents[1]
        env=dict(os.environ,GH_TOKEN='synthetic-host',OPENAI_API_KEY='synthetic-provider',SSH_AUTH_SOCK='synthetic-socket')
        scope={'os':os,'sanitized_environ':lambda:dict(env),'Path':Path}
        def load(path,name):
            node=next(n for n in ast.parse((root/path).read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
        load(Path('open_terminal/utils/git.py'),'git_environment')
        load(Path('open_terminal/agents/sessions.py'),'identity')
        scope['os']=SimpleNamespace(path=os.path,pathsep=os.pathsep,getuid=lambda:1000)
        pwd=SimpleNamespace(getpwnam=lambda _:SimpleNamespace(pw_dir='/fixture-user',pw_uid=1000,pw_gid=1000))
        with patch.dict(sys.modules,{'pwd':pwd}):
            actual,_,_=scope['identity'](SimpleNamespace(username='fixture',home='/fixture-user'))
        for key in ['GH_TOKEN','OPENAI_API_KEY','SSH_AUTH_SOCK']:self.assertNotIn(key,actual)

    async def test_default_and_false_setting_never_spawn_cline(self):
        source=Path(__file__).resolve().parents[1]/'open_terminal/agents/discovery.py'
        node=next(n for n in ast.parse(source.read_text('utf-8')).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='probe')
        spawn=AsyncMock(side_effect=RuntimeError('synthetic spawn reached'))
        scope={'os':os,'HTTPException':HTTPException,'sessions':SimpleNamespace(spawn=spawn,Start=SimpleNamespace),'asyncio':asyncio}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
        for value in ['', 'false']:
            with patch.dict(os.environ,{'OPEN_TERMINAL_ALLOW_CLINE_DISCOVERY':value}):
                with self.assertRaises(HTTPException):await scope['probe']('cline',object())
        spawn.assert_not_awaited()
        with patch.dict(os.environ,{'OPEN_TERMINAL_ALLOW_CLINE_DISCOVERY':'true'}):
            with self.assertRaisesRegex(RuntimeError,'synthetic spawn reached'):
                await scope['probe']('cline',object())
        self.assertEqual(spawn.await_count,1)


if __name__=='__main__':unittest.main()
