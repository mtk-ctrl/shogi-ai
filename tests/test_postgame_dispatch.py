import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('dispatch_postgame',Path(__file__).parents[1]/'.github/scripts/dispatch_postgame_pilot.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DispatchTests(unittest.TestCase):
    def request(self):
        return dict(request_id=m.REQUEST_ID,candidate_ref=m.CANDIDATE,baseline_ref=m.PARENT,games=100,shards=20)
    def test_frozen_screen(self):
        self.assertEqual(m.validate(self.request())['shards'],20)
    def test_reject_changed_budget_refs_or_commands(self):
        for key,value in [('games',300),('games',True),('shards',21),('shards',True),('candidate_ref','main'),('baseline_ref','main'),('request_id','another'),('command','anything')]:
            with self.subTest(key=key,value=value):
                d=self.request();d[key]=value
                with self.assertRaises(ValueError):m.validate(d)
    def test_confirmation_requires_fixed_id_and_audited_predecessor(self):
        d=self.request();d.update(games=200,request_id='postgame-g1-confirm-20261017',previous_audit_run=123)
        self.assertEqual(m.validate(d)['games'],200)
        d['previous_audit_run']=0
        with self.assertRaises(ValueError):m.validate(d)
    def test_duplicate_only_same_manual_operation(self):
        rows=[dict(id=1,event='workflow_dispatch',display_title='Postgame '+m.REQUEST_ID),dict(id=2,event='pull_request',display_title='Postgame '+m.REQUEST_ID),dict(id=3,event='workflow_dispatch',display_title='Postgame other')]
        self.assertEqual([r['id'] for r in m.existing(rows,m.REQUEST_ID)],[1])
if __name__=='__main__':unittest.main()
