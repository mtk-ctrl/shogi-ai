import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import shogi
import torch
from tools.research import neural_model as nm, neural_residual as nr, neural_cluster as nc
from tools.research.neural_arena import options


class ResidualTests(unittest.TestCase):
    def test_zero_start_cap_format_and_no_policy_override(self):
        net=nm.Network(16,correction=True)
        rows=[dict(features=nm.features(shogi.Board().sfen()))]
        self.assertEqual(net(*nm.tensors(rows,'cpu'))[0].item(),0)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.nnue'
            nm.export_nnue(net,path)
            self.assertEqual(path.read_bytes()[:8],b'KMNNUE04')
            self.assertEqual(nm.quantized_cp(path,shogi.Board().sfen()),0)
            self.assertFalse(options('position-knowledge-v1.tsv',path)['EvalNeuralPolicy'])
            with torch.no_grad():net.value.bias.fill_(3)
            nm.export_nnue(net,path)
            self.assertEqual(nm.quantized_cp(path,shogi.Board().sfen()),600)
            self.assertAlmostEqual(net(*nm.tensors(rows,'cpu'))[0].item(),.6,places=6)
        with self.assertRaises(ValueError):nm.Network(16,correction=True,material_prior=True)

    def test_targets_are_absolute_minus_native_baseline_and_cached(self):
        row=dict(root='test',sfen=shogi.Board().sfen(),target=.9,policy_weight=.2)
        parts={name:[dict(row)] for name in ('train','validation','test')}
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'binary';binary.write_bytes(b'own engine')
            cache=Path(tmp)/'cache.json'
            with patch.object(nr,'StaticOracle') as oracle:
                oracle.return_value.evaluate.return_value=500
                transformed=nr.correction_targets(parts,binary,cache)
                self.assertAlmostEqual(transformed['train'][0]['target'],.4)
                self.assertEqual(parts['train'][0]['target'],.9)
                self.assertEqual(transformed['test'][0]['baseline_cp'],500)
                oracle.return_value.evaluate.assert_called_once()
                nr.correction_targets(parts,binary,cache)
                oracle.return_value.evaluate.assert_called_once()
                with self.assertRaisesRegex(ValueError,'already applied'):
                    nr.correction_targets(transformed,binary,cache)
            binary.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):nr.correction_targets(parts,binary,cache)

    def test_five_is_finite_and_invalid_modes_rejected(self):
        self.assertEqual(nc.parameters(dict(generations=5,evaluation_mode='correction'))['generations'],5)
        with self.assertRaises(ValueError):nc.parameters(dict(generations=6))
        with self.assertRaises(ValueError):nc.parameters(dict(evaluation_mode='unknown'))


if __name__=='__main__':unittest.main()
