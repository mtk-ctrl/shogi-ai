#!/usr/bin/env python3
"""Read-only replay of two saved no-pair diagnoses; no engine or new games.

The original preparation must reproduce exactly before new diagnostics are
attached. If recorded cases need fresh probes, reject rather than invent them.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.research.postgame_ranker import require
from tools.research.postgame_spiral import prepare
from tools.research.postgame_progress import POLICY_PROGRESS, describe, record

spec = importlib.util.spec_from_file_location('progress_replay_backend', ROOT/'.github/scripts/run_postgame_spiral.py')
backend = importlib.util.module_from_spec(spec); spec.loader.exec_module(backend)

PACKAGES = (
    ('spiral-spiral-auto-smoke-20261017-01-prepare-d8afbfefa370b08f-39021709686-a1.tgz',
     '8d849163d928ca5941f2f76a1251d22e3104229b795fcf56853978c26ec46d47', 13074),
    ('spiral-spiral-auto-smoke-20261017-01-prepare-f30c8976c1134849-39021709686-a1.tgz',
     'dee7e019af56fe8b8cc70f3e2bc02fccb8f35b2b1f9b9b6af29d3251cc449b2b', 15249),
)


def replay(directory, download=False, on_preparation=None):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    previous = {}; progress = None; reports = []
    def missing(*_):
        raise ValueError('Saved evidence requires unavailable parent/static probes; do not fabricate them')
    for generation, (name, expected, size) in enumerate(PACKAGES, 1):
        package = directory/name
        url = 'https://github.com/mtk-ctrl/shogi-ai/releases/download/records-2026-10-01/'+name
        if not package.exists():
            require(download, 'Provide verified input packages or explicitly request download')
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read()
            require(len(data) == size and hashlib.sha256(data).hexdigest() == expected, 'downloaded research package differs')
            package.write_bytes(data)
        raw = package.read_bytes()
        require(len(raw) == size and hashlib.sha256(raw).hexdigest() == expected, 'saved research package differs')
        # Preserve source archives; extract selected research into a new folder.
        folder = directory/('unpacked-'+str(generation))
        folder.mkdir(exist_ok=True); backend.safe_extract(package, folder)
        original = json.loads((folder/'preparation.json').read_bytes())
        diagnosis = json.loads((folder/'analysis/diagnosis.json').read_bytes())
        analysis = json.loads((folder/'analysis/summary.json').read_bytes())
        context = original['example_bank']['parent_context']
        report = prepare(diagnosis, missing, missing, 'spiral-bridge-20261017-v1',
                         registry=previous.get('split_registry'), example_bank=previous.get('example_bank'),
                         parent_context=context, parent_options=original['learning']['parent_options'],
                         track_decisions=True)
        report['invalidated_old_parent_features'] = original['invalidated_old_parent_features']
        require({k:v for k,v in report.items() if k != 'case_decisions'} == original,
                'Original guarded preparation did not reproduce exactly')
        report['progress'] = describe(report, analysis, diagnosis, context)
        if on_preparation is not None:
            on_preparation(report,diagnosis,context,generation,folder)
        state = dict(plan=dict(cycle_id='saved-diagnosis-review', progress_policy=POLICY_PROGRESS),
                     generation=generation, parent=context)
        if progress:
            state.update(progress_history=progress['history'], research_followup=progress)
        progress = record(state, report)
        reports.append(dict(generation=generation, package=dict(name=name,sha256=expected,bytes=size,url=url),
                            original_preparation_reproduced=True, statistics=report['progress']['statistics'],
                            task_counts=report['progress']['task_counts'], halt_collection=progress['halt_collection'],
                            next_action=progress['next_action'], reason=progress['reason']))
        previous = original
    return dict(schema='postgame-progress-saved-replay-v1', original_cycle='spiral-auto-smoke-20261017-01',
                scope='Offline assessment of saved diagnoses under the new policy; original execution/result unchanged.',
                new_games=0, engine_executions=0, new_analysis=0, parameter_updates=0, formal_adoption=False,
                strength_improvement_demonstrated=False, generations=reports,
                work_items=[dict(task_id=t['task_id'],kind=t['kind'],case_id=t['case']['case_id'],
                                 source=t['case']['source'],evidence=t['evidence'],status=t['status'])
                            for t in progress['work_items']],
                final_next_action=progress['next_action'], final_reason=progress['reason'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path,default=Path('build/progress-readback'))
    p.add_argument('--download',action='store_true');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();report=replay(args.input_dir,args.download)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('generations','work_items')}))


if __name__=='__main__':main()
