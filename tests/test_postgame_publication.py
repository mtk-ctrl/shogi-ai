import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('postgame_pub',ROOT/'.github/scripts/publish_postgame.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
START='lnsgkgsnl/1r5b1/ppppppppp/9/9/9/PPPPPPPPP/1B5R1/LNSGKGSNL b - 1'
COMMAND='position sfen '+START


class PublicationTest(unittest.TestCase):
    def prepare(self,root,change=None,link=False):
        binary=b'ELF test fixture';digest=m.sha(binary)
        c={'case_id':'test','source':{'run_id':1,'game_id':'game'},'start_sfen':START,
           'history_moves':[],'actual_move':'7g7f','analysis_position_command':COMMAND}
        f={'position_command':COMMAND,'history_key':m.sha(COMMAND.encode())}
        r={'case':c,'root_short':dict(f,requested_ms=50),'root_deep':dict(f,requested_ms=500)}
        docs={'summary.json':dict(status='diagnosis_completed',learning_status='not_run',formal_adoption=False,
                  source_games=500,source_plies=54821,selected_cases=1,knowledge_sha256=m.KNOWLEDGE,
                  analyzer_binary_sha256=digest),
              'analyzer-build.json':{'binary_sha256':digest},'input-receipts.json':[],
              'attribution.json':[],'selected-cases.json':[c],'diagnosis.json':[r]}
        if change:change(docs)
        files={name:json.dumps(value).encode() for name,value in docs.items()};files['postgame-analyzer']=binary
        p=root/m.PAYLOAD;p.parent.mkdir(parents=True)
        with tarfile.open(p,'w:gz') as t:
            for name,data in files.items():
                info=tarfile.TarInfo(name);info.size=len(data)
                if link and name=='postgame-analyzer':info.type=tarfile.SYMTYPE;info.linkname='/tmp/untrusted'
                t.addfile(info,io.BytesIO(data) if info.isfile() else None)
        manifest=dict(schema='kumoji-postgame-publication-v1',operation_id='postgame-diagnosis-20261017-01',
                      payload_path=m.PAYLOAD,sha256=m.sha(p.read_bytes()),bytes=p.stat().st_size,
                      files={name:dict(sha256=m.sha(data),bytes=len(data)) for name,data in files.items()})
        (root/m.MANIFEST).write_text(json.dumps(manifest))
        return p

    def test_valid_selected_research_and_binary(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.prepare(root);manifest,summary=m.verify(root)
            self.assertEqual(summary['selected_cases'],1)

    def test_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.prepare(root);p.write_bytes(p.read_bytes()+b'corrupt')
            with self.assertRaises(ValueError):m.verify(root)

    def test_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.prepare(root,link=True)
            with self.assertRaises(ValueError):m.verify(root)

    def test_pv_and_mismatched_case_or_binary_are_rejected(self):
        changes=[lambda x:x['diagnosis.json'][0].update(pv=['7g7f']),
                 lambda x:x['diagnosis.json'][0]['root_deep'].update(position_command='position startpos'),
                 lambda x:x['summary.json'].update(analyzer_binary_sha256='wrong'),
                 lambda x:x['summary.json'].update(selected_cases=2),
                 lambda x:x['selected-cases.json'][0].update(actual_move='7g7e')]
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                root=Path(d);self.prepare(root,change)
                with self.assertRaises(ValueError):m.verify(root)


if __name__=='__main__':unittest.main()
