"""Dispatch only the frozen, owner-authorized postgame pilot screen."""
import json
import os
from pathlib import Path
import re
import subprocess

CANDIDATE='5a1997043f275d09099c4be67110ed96e2c80c88'
PARENT='efcfa0f80d218c3dbcc3162f5bee3366f6a835cf'
WORKFLOW='postgame-cycle-pilot.yml'
REQUEST_ID='postgame-g1-screen-20261017'

def validate(d):
    if set(d)!={'request_id','candidate_ref','baseline_ref','games','shards'}:
        raise ValueError('request keys')
    if d['request_id']!=REQUEST_ID or d['candidate_ref']!=CANDIDATE or d['baseline_ref']!=PARENT:
        raise ValueError('frozen screen identity')
    if type(d['games']) is not int or d['games']!=100:
        raise ValueError('screen budget')
    if type(d['shards']) is not int or not 1<=d['shards']<=20:
        raise ValueError('runner count')
    return d

def existing(runs,request_id):
    return [r for r in runs if r.get('event')=='workflow_dispatch' and r.get('display_title')=='Postgame '+request_id]

def gh(*args):
    return subprocess.check_output(['gh',*map(str,args)],text=True)

def main():
    d=validate(json.loads(Path('.github/postgame-pilot-request.json').read_text()))
    repo=os.environ['GITHUB_REPOSITORY']
    runs=json.loads(gh('api',f'repos/{repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100'))['workflow_runs']
    found=existing(runs,d['request_id'])
    if found:
        print('EXISTING_POSTGAME_RUNS '+json.dumps([r['id'] for r in found]));return
    # This is an explicit request, not a periodic or workflow-file push trigger.
    subprocess.run(['gh','workflow','run',WORKFLOW,'--repo',repo,'--ref','main',
                    '-f','candidate_ref='+d['candidate_ref'],'-f','games=100',
                    '-f','shards='+str(d['shards']),'-f','request_id='+d['request_id']],check=True)
    print('POSTGAME_DISPATCH_REQUESTED '+json.dumps(d))

if __name__=='__main__':main()
