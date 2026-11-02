import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock
from starlette.background import BackgroundTask

scope={'time':NS(time=lambda:1000),'PROCESS_EXPIRY':300,'PROCESS_UNDELIVERED_EXPIRY':1800,
       'BackgroundTask':BackgroundTask,'_processes':{},'asyncio':asyncio,'_process_list_changed':asyncio.Event()}
tree=ast.parse((Path(__file__).resolve().parents[1]/'open_terminal/main.py').read_text('utf-8'))
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {'_cleanup_expired','_process_log_response','_notify_process_list'}]
assert len(nodes)==3
exec(compile(ast.Module(body=nodes,type_ignores=[]),'actual-result-retention','exec'),scope)

class ResultDelivery(unittest.IsolatedAsyncioTestCase):
    def test_unread_and_running_results_remain_available(self):
        items={'unread':NS(id='unread',finished_at=100,delivered_at=None),
          'read':NS(id='read',finished_at=100,delivered_at=600),
          'ancient':NS(id='ancient',finished_at=-1000,delivered_at=None),
          'running':NS(id='running',finished_at=None,delivered_at=None)}
        scope['_processes']=items;scope['_cleanup_expired']()
        self.assertEqual(set(items),{'unread','running'})
    async def test_only_completed_delivery_starts_short_expiry(self):
        cleanup=AsyncMock();response=NS(background=cleanup)
        scope['log_response']=AsyncMock(return_value=response)
        process=NS(log_path='fixture',delivered_at=None)
        result=await scope['_process_log_response'](process,{'status':'completed'})
        self.assertIsNone(process.delivered_at)
        await result.background()
        self.assertEqual(process.delivered_at,1000);cleanup.assert_awaited_once()
    async def test_running_snapshot_never_marks_final_result_delivered(self):
        cleanup=AsyncMock();scope['log_response']=AsyncMock(return_value=NS(background=cleanup))
        process=NS(log_path='fixture',delivered_at=None)
        result=await scope['_process_log_response'](process,{'status':'running'})
        await result.background();self.assertIsNone(process.delivered_at)

if __name__=='__main__':unittest.main()
