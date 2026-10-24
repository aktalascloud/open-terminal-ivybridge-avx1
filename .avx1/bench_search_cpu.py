"""Measure preview construction and the real authenticated grep API on this CPU."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import statistics
import tempfile
import time
from unittest.mock import patch

OLD=r'''def old_preview(line, match_start):
    content=line.rstrip("\r\n")
    if len(content)<=300:return content
    left=max(0,match_start-100);right=min(len(content),left+300);left=max(0,right-300)
    return (("…" if left else "")+content[left:right]+("…" if right<len(content) else "")+f" [truncated; columns {left+1}-{right} of {len(content)}]")
'''

def main(output):
    root=Path(__file__).resolve().parents[1]
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('preview_candidate',root/'open_terminal/utils/search_preview.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);current=mod.bounded_match_content
    namespace={};exec(OLD,namespace);old=namespace['old_preview']
    r=random.Random(19)
    for length in [0,1,298,299,300,301,302,1000,2000006]:
        for ending in ('','\n','\r\n','\r\r\n'):
            text=('жяx'*(length//3+1))[:length]+ending
            for location in (0,length//2,max(0,length-1)):assert current(text,location)==old(text,location)
    line='a'*1000000+'needle'+'b'*1000000+'\n';samples={'released_preview':[],'slice_only_preview':[]}
    for turn in range(10):
        for label,fn in ([('released_preview',old),('slice_only_preview',current)] if turn%2==0 else [('slice_only_preview',current),('released_preview',old)]):
            for _ in range(10):fn(line,1000000)
            count=1000
            while True:
                start=time.process_time_ns()
                for _ in range(count):fn(line,1000000)
                elapsed=time.process_time_ns()-start
                if elapsed>=200000000:break
                count*=2
            samples[label].append(elapsed/count)
    result={'cpu':platform.processor(),'scope':'Synthetic 2MB matching line: preview construction CPU time; no LLM inference. Old/released and optimized outputs are identical.',
            'semantic_comparisons':108,'input_chars':len(line),'preview_samples_cpu_ns':samples,
            'source_sha256':hashlib.sha256((root/'open_terminal/utils/search_preview.py').read_bytes()).hexdigest()}
    med={k:statistics.median(v) for k,v in samples.items()};result['preview_cpu_median_ns']=med;result['preview_cpu_time_reduction_percent']=100*(1-med['slice_only_preview']/med['released_preview'])
    with tempfile.TemporaryDirectory(prefix='owui-grep-cpu-',dir=Path(output).parent) as folder:
        os.environ.update(OPEN_TERMINAL_API_KEY='synthetic-cpu-benchmark',OPEN_TERMINAL_MULTI_USER='false',OPEN_TERMINAL_ENABLE_TERMINAL='false',OPEN_TERMINAL_ENABLE_NOTEBOOKS='false',OPEN_TERMINAL_LOG_DIR=folder,XDG_STATE_HOME=folder,XDG_CONFIG_HOME=folder)
        os.environ.pop('OPEN_TERMINAL_API_KEY_FILE',None)
        import open_terminal.main as service
        from fastapi.testclient import TestClient
        path=Path(folder)/'data.json';path.write_text(line,encoding='utf-8')
        headers={'Authorization':'Bearer synthetic-cpu-benchmark'};params={'query':'needle','path':str(path)}
        timings={'upstream_full_line':[],'released_preview':[],'slice_only_preview':[]};sizes={}
        with TestClient(service.app) as client:
            assert client.get('/files/grep',params=params).status_code==401
            cases=[('upstream_full_line',lambda text,pos:text.rstrip('\r\n')),('released_preview',old),('slice_only_preview',current)]
            for turn in range(6):
                order=cases if turn%2==0 else list(reversed(cases))
                for label,fn in order:
                    with patch.object(service,'bounded_match_content',fn):
                        probe=client.get('/files/grep',params=params,headers=headers);assert probe.status_code==200
                        data=probe.json();assert len(data['matches'])==1 and data['matches'][0]['line']==1 and 'needle' in data['matches'][0]['content'];sizes[label]=len(probe.content)
                        start=time.process_time_ns()
                        for _ in range(200):
                            response=client.get('/files/grep',params=params,headers=headers);assert response.status_code==200
                        timings[label].append((time.process_time_ns()-start)/200)
        medians={k:statistics.median(v) for k,v in timings.items()};result.update(api_samples_cpu_ns=timings,api_cpu_median_ns=medians,response_bytes=sizes,
            api_cpu_time_reduction_vs_upstream_percent=100*(1-medians['slice_only_preview']/medians['upstream_full_line']),
            api_cpu_time_reduction_vs_released_percent=100*(1-medians['slice_only_preview']/medians['released_preview']))
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if 'samples' not in k}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args();main(args.output)
