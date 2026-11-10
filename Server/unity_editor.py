"""Small local client for the installed Unity Pipeline package (keeps its token private)."""
import argparse, json, urllib.request, urllib.error
from pathlib import Path

def execute(project, command, parameters=None):
    descriptor=json.loads((Path(project)/'Library/Pipeline/.unity-pipeline-port').read_text())
    request=urllib.request.Request(f'http://127.0.0.1:{descriptor["port"]}/api/exec',
        data=json.dumps({'command':command,'parameters':parameters or {}}).encode(),
        headers={'Content-Type':'application/json','Authorization':'Bearer '+descriptor['evalToken']})
    try:
        with urllib.request.urlopen(request,timeout=55) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        return {'http_status':error.code,'error':error.read().decode(errors='replace')}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('command');p.add_argument('parameters',nargs='?',default='{}')
    a=p.parse_args();print(json.dumps(execute(a.project,a.command,json.loads(a.parameters)),indent=2))
