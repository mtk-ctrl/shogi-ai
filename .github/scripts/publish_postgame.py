"""Verify and preserve one bounded local postgame diagnosis; execute no payload."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import shogi

PAYLOAD='research/selfplay-postgame-20261017/initial-diagnosis.tgz'
MANIFEST='research/selfplay-postgame-20261017/initial-publication.json'
NAMES={'selected-cases.json','diagnosis.json','summary.json','attribution.json',
       'analyzer-build.json','input-receipts.json','postgame-analyzer'}
KNOWLEDGE='6da204cd1e65600ccdbb9f3dbe463627687d6cf7eb8347da6a103239129dac4c'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def require(test,message):
    if not test:raise ValueError(message)
def no_pv(value):
    if isinstance(value,dict):
        require(not (set(value)&{'pv','candidates','search_tree','raw_log'}),'unplayed trees/PVs in publication')
        for v in value.values():no_pv(v)
    elif isinstance(value,list):
        for v in value:no_pv(v)


def verify(candidate):
    candidate=Path(candidate)
    m=json.loads((candidate/MANIFEST).read_text())
    require(m['schema']=='kumoji-postgame-publication-v1','publication schema')
    require(m['operation_id']=='postgame-diagnosis-20261017-01','operation ID')
    require(m['payload_path']==PAYLOAD,'payload path')
    raw=(candidate/PAYLOAD).read_bytes()
    require(len(raw)==m['bytes'] and len(raw)<16*1024*1024,'payload bytes')
    require(sha(raw)==m['sha256'],'payload SHA256')
    require(set(m['files'])==NAMES,'manifest file allowlist')
    files={}
    with tarfile.open(candidate/PAYLOAD) as archive:
        members=archive.getmembers()
        require(len(members)==len(NAMES) and {x.name for x in members}==NAMES,'tar allowlist/duplicate')
        for member in members:
            require(member.isfile() and 0<=member.size<16*1024*1024,'tar member type/size')
            data=archive.extractfile(member).read()
            require(sha(data)==m['files'][member.name]['sha256'] and len(data)==m['files'][member.name]['bytes'],'member hash/bytes')
            files[member.name]=data
    docs={name:json.loads(data) for name,data in files.items() if name.endswith('.json')}
    for doc in docs.values():no_pv(doc)
    s=docs['summary.json'];build=docs['analyzer-build.json']
    require(s['status']=='diagnosis_completed' and s['learning_status']=='not_run' and s['formal_adoption'] is False,'research status')
    require(s['source_games']==500 and s['source_plies']==54821,'source count')
    require(s['knowledge_sha256']==KNOWLEDGE,'knowledge hash')
    require(s['analyzer_binary_sha256']==build['binary_sha256']==sha(files['postgame-analyzer']),'actual analyzer binary hash')
    cases=docs['selected-cases.json'];results=docs['diagnosis.json']
    require(0<len(cases)==len(results)==s['selected_cases']<=96,'case count')
    require(len({c['case_id'] for c in cases})==len(cases),'duplicate cases')
    require([c['case_id'] for c in cases]==[r['case']['case_id'] for r in results],'case/result identity')
    counts={}
    for c,r in zip(cases,results):
        key=(c['source']['run_id'],c['source']['game_id'])
        counts[key]=counts.get(key,0)+1
        require(counts[key]<=4,'per-game budget')
        board=shogi.Board(c['start_sfen'])
        for token in c['history_moves']:
            move=shogi.Move.from_usi(token);require(move in board.legal_moves,'illegal history');board.push(move)
        require(shogi.Move.from_usi(c['actual_move']) in board.legal_moves,'illegal actual move')
        command='position sfen '+c['start_sfen']+(' moves '+' '.join(c['history_moves']) if c['history_moves'] else '')
        require(c['analysis_position_command']==command,'analysis history command')
        for field in ('root_short','root_deep'):
            frame=r[field]
            require(frame['position_command']==command and frame['history_key']==sha(command.encode()),'root history proof')
        require(r['root_short']['requested_ms']==50 and r['root_deep']['requested_ms']==500,'analysis budgets')
    return m,s


def publish(candidate, output, repo):
    m,summary=verify(candidate)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    def run(*args):return subprocess.check_output(['gh',*map(str,args)],text=True)
    tag='records-2026-10-01';name=m['operation_id']+'.tgz'
    release=json.loads(run('api',f'repos/{repo}/releases/tags/{tag}'))
    require(len(release['assets'])<800,'monthly release rollover needed')
    existing=[a for a in release['assets'] if a['name']==name]
    require(len(existing)<=1,'duplicate asset name')
    package=output/name
    package.write_bytes((Path(candidate)/PAYLOAD).read_bytes())
    if not existing:run('release','upload',tag,package,'--repo',repo)
    readback=output/'postgame-readback';readback.mkdir(exist_ok=True)
    target=readback/name
    if target.exists():target.unlink()
    run('release','download',tag,'--repo',repo,'--pattern',name,'--dir',readback)
    require(sha(target.read_bytes())==m['sha256'],'Release readback hash mismatch; do not overwrite')
    fresh=json.loads(run('api',f'repos/{repo}/releases/tags/{tag}'))
    asset=next(a for a in fresh['assets'] if a['name']==name)
    require(asset['size']==m['bytes'] and asset.get('digest')=='sha256:'+m['sha256'],'Release API digest/bytes mismatch')
    publication=dict(release=tag,name=name,sha256=m['sha256'],bytes=m['bytes'],readback_verified=True,
                     api_digest_verified=True,url=asset['browser_download_url'],release_asset_count=len(fresh['assets']),
                     release_total_bytes=sum(a['size'] for a in fresh['assets']),
                     repository_staging_bytes=m['bytes'],repository_staging_note='One initial transfer snapshot; not an ongoing played-game archive. Git history retains this initial snapshot.')
    report=dict(mode='postgame-publish',summary=summary,publication=publication,
                code_ref=m['code_ref'],formal_adoption=False,storage='Full selected diagnosis and exact local analyzer binary verified in monthly data Release.')
    (output/'publication.json').write_text(json.dumps(publication,indent=2)+'\n')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
