"""Hosted transport failure boundaries; no network operations in unit tests."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cluster_actions',ROOT/'.github/scripts/neural_cluster_actions.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


class TransportTests(unittest.TestCase):
    def test_cleanup_is_scoped_to_durably_saved_generation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GITHUB_REPOSITORY':'owner/repo','GITHUB_RUN_ID':'123'}):
            old=Path.cwd();os.chdir(tmp)
            try:
                Path('publication-receipt.json').write_text(json.dumps({'verified':False}))
                with self.assertRaises(ValueError):a.prune('neural20-g0')
                Path('publication-receipt.json').write_text(json.dumps({'verified':True}))
                rows=[dict(id=i,name=name,size_in_bytes=3) for i,name in enumerate([
                    'unrelated','neural20-g0-study-0','neural20-g0-complete-state',
                    'neural20-g0-publication','neural20-g1-study-0'])]
                with patch.object(a,'api',return_value={'artifacts':rows}),patch.object(a,'gh') as gh:
                    a.prune('neural20-g0')
                    gh.assert_called_once_with('api','--method','DELETE','repos/owner/repo/actions/artifacts/1')
            finally:os.chdir(old)

    def test_reducer_restores_own_checkpoint_when_old_input_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path.cwd();os.chdir(tmp)
            try:
                Path('resume').mkdir();Path('resume/state.tgz').write_bytes(b'checkpoint')
                with patch.object(a.nc,'unpack') as unpack:
                    a.restore_input()
                    unpack.assert_called_once_with(Path('resume/state.tgz'),'run')
            finally:os.chdir(old)


if __name__=='__main__':unittest.main()
