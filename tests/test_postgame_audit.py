import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock
spec=importlib.util.spec_from_file_location('audit_postgame',Path(__file__).parents[1]/'.github/scripts/audit_postgame_pilot.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class AuditTests(unittest.TestCase):
    def row(self):
        games=[dict(a_black=i%2==0,moves=[],move_records=[],winner='A') for i in range(5)]
        return dict(games=5,details=games,game_offset=0,seed=2031101801,go_command='go movetime 200',max_plies=300,illegal_games=0,sha256_a='binary',sha256_b='binary',options_a=m.options('A'),options_b=m.options('B'),position_knowledge={'A':dict(enabled=True,available=True,sha256=m.K1,positions=165),'B':dict(enabled=True,available=True,sha256=m.K0,positions=163)},wins_a=5,wins_b=0,draws=0)
    def test_trajectory_and_score_sensitivity(self):
        start='board b - 1'
        self.assertEqual(m.trajectory(start,['7g7f']),m.trajectory('board b - 50',['7g7f']))
        self.assertNotEqual(m.trajectory(start,['7g7f']),m.trajectory('board w - 1',['7g7f']))
        self.assertEqual(m.subset_result([{'winner':'A'},{'winner':'B'},{'winner':None}])['score_a'],.5)
    def test_log_controls_removed_and_redirect_has_no_auth(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'\x1b[31mcommit SHA\x1b[0m'
        opener=MagicMock();opener.open.return_value=response
        with patch.dict(m.os.environ,GH_TOKEN='test-token'),patch.object(m,'build_opener',return_value=opener) as build:
            self.assertEqual(m.sanitized_job_log('owner/repo',1),'commit SHA')
            request=m.Request('https://api.github.com/a',headers={'Authorization':'Bearer test-token'})
            redirect=build.call_args.args[0].redirect_request(request,None,302,'',{},'https://example.com/signed-log')
            self.assertFalse(redirect.has_header('Authorization'))
    def test_all_legal_replays_called(self):
        with patch.object(m,'verify_game') as replay:
            m.validate_shard(self.row(),0,'binary');self.assertEqual(replay.call_count,5)
    def test_reject_identity_option_knowledge_and_color_drift(self):
        for change in ['seed','binary','options','knowledge','color','total']:
            r=self.row()
            if change=='seed':r['seed']+=1
            if change=='binary':r['sha256_b']='other'
            if change=='options':r['options_a']['USI_Ponder']=False
            if change=='knowledge':r['position_knowledge']['B']['sha256']=m.K1
            if change=='color':r['details'][1]['a_black']=True
            if change=='total':r['wins_b']=1
            with self.subTest(change=change),patch.object(m,'verify_game'),self.assertRaises(ValueError):m.validate_shard(r,0,'binary')
    def test_unverified_terminal_propagates(self):
        with patch.object(m,'verify_game',side_effect=ValueError('invalid terminal')),self.assertRaises(ValueError):m.validate_shard(self.row(),0,'binary')
if __name__=='__main__':unittest.main()
