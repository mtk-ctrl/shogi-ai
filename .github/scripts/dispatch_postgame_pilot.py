"""Dispatch only the frozen, owner-authorized postgame pilot screen."""
import argparse
import json
import tempfile
import os
from pathlib import Path
import re
import subprocess

CANDIDATE='5a1997043f275d09099c4be67110ed96e2c80c88'
PARENT='efcfa0f80d218c3dbcc3162f5bee3366f6a835cf'
WORKFLOW='postgame-cycle-pilot.yml'
REQUEST_ID='postgame-g1-screen-20261017'

def validate(d):
    required={'request_id','candidate_ref','baseline_ref','games','shards'}
    if d.get('games')==200:required.add('previous_audit_run')
    if set(d)!=required:raise ValueError('request keys')
    if d['candidate_ref']!=CANDIDATE or d['baseline_ref']!=PARENT:raise ValueError('frozen refs')
    if type(d['games']) is not int or d['games'] not in (100,200):raise ValueError('game budget')
    expected=REQUEST_ID if d['games']==100 else 'postgame-g1-confirm-20261017'
    if d['request_id']!=expected:raise ValueError('frozen operation identity')
    if type(d['shards']) is not int or not 1<=d['shards']<=20:raise ValueError('runner count')
    if d['games']==200 and (type(d['previous_audit_run']) is not int or d['previous_audit_run']<=0):raise ValueError('previous audit run')
    return d

def existing(runs,request_id):
    return [r for r in runs if r.get('event')=='workflow_dispatch' and r.get('display_title')=='Postgame '+request_id]

def gh(*args):
    return subprocess.check_output(['gh',*map(str,args)],text=True)

def validate_confirmation(audit_run,repo):
    info=json.loads(gh('api',f'repos/{repo}/actions/runs/{audit_run}'))
    if info['status']!='completed' or info['conclusion']!='success':raise ValueError('screen audit unfinished')
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(['gh','run','download',str(audit_run),'--repo',repo,'--name',f'selfplay-verification-{audit_run}','--dir',folder],check=True)
        a=json.loads((Path(folder)/'audit.json').read_text());p=json.loads((Path(folder)/'publication.json').read_text())
        if (a['match_run'],a['games'],a['candidate_ref'],a['parent_ref'])!=(39005539549,100,CANDIDATE,PARENT):raise ValueError('wrong screen evidence')
        if a['score_a']<.5 or not all(a.get(k) is True for k in ('legal_replay','termination_rules_verified','conditions_verified')):raise ValueError('screen gate failed')
        if not p.get('readback_verified') or not p.get('api_digest_verified'):raise ValueError('screen audit not preserved')
        release=json.loads(gh('api',f"repos/{repo}/releases/tags/{p['release']}"))
        assets=[x for x in release['assets'] if x['name']==p['name']]
        if len(assets)!=1 or assets[0]['size']!=p['bytes'] or assets[0].get('digest')!='sha256:'+p['sha256']:raise ValueError('audit receipt mismatch')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--plan-only',action='store_true');args=parser.parse_args()
    d=validate(json.loads(Path('.github/postgame-pilot-request.json').read_text()))
    repo=os.environ['GITHUB_REPOSITORY']
    runs=json.loads(gh('api',f'repos/{repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=100'))['workflow_runs']
    found=[r for r in existing(runs,d['request_id']) if r['id']!=int(os.environ['GITHUB_RUN_ID'])]
    if found:
        if args.plan_only:raise ValueError('operation already exists')
        print('EXISTING_POSTGAME_RUNS '+json.dumps([r['id'] for r in found]));return
    if d['games']==200:validate_confirmation(d['previous_audit_run'],repo)
    if args.plan_only:
        if str(d['candidate_ref'])!=os.environ['CANDIDATE_REF'] or str(d['games'])!=os.environ['GAMES'] or str(d['shards'])!=os.environ['SHARDS'] or d['request_id']!=os.environ['REQUEST_ID']:raise ValueError('manual inputs/request mismatch')
        return
    command=['gh','workflow','run',WORKFLOW,'--repo',repo,'--ref','main','-f','candidate_ref='+d['candidate_ref'],'-f','games='+str(d['games']),'-f','shards='+str(d['shards']),'-f','request_id='+d['request_id']]
    subprocess.run(command,check=True)
    print('POSTGAME_DISPATCH_REQUESTED '+json.dumps(d))

if __name__=='__main__':main()
