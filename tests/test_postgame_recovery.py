"""Freeze/authorization guards for one-generation salvage from saved played games."""
import unittest
from tools.research.postgame_runtime import initialize
from tools.research.postgame_ranker import BASE,OPTIONS
from tests.test_postgame_runtime import plan

def recovered():
    p=plan(generations=1,budget=300)
    p.update(source_games=100,generate_initial_source=False,max_new_games=300,
             recovery_cycle_id='previous-blocked-cycle',
             recovery_checkpoint=dict(name='state-000008.json',release='records-2026-10-01',
                                      sha256='a'*64,bytes=100,
                                      readback_verified=True,api_digest_verified=True),
             source_publication=dict(name='initial-source.tgz',release='records-2026-10-01',
                                     sha256='b'*64,bytes=123,
                                     readback_verified=True,api_digest_verified=True))
    return p

class RecoveryTest(unittest.TestCase):
    def test_preserved_source_starts_at_analysis_not_new_games(self):
        p=recovered();e=initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)
        self.assertEqual(e['state']['stage'],'prepare')
        self.assertEqual(e['state']['used_games'],0)
        self.assertEqual(e['source_publication'],p['source_publication'])

    def test_incomplete_recovery_identity_is_rejected(self):
        for key,value in [('source_publication',None),('recovery_cycle_id','synthetic-runtime-test'),
                          ('generate_initial_source',True),('max_generations',2),('max_new_games',601)]:
            p=recovered();p[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)

    def test_unverified_recovery_file_is_rejected(self):
        p=recovered();p['source_publication']['api_digest_verified']=False
        with self.assertRaises(ValueError): initialize(p,dict(zip(OPTIONS,BASE)),'c'*64)

if __name__=='__main__':unittest.main()
