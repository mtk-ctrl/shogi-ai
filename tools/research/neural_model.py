#!/usr/bin/env python3
"""Own king-conditioned policy/value research network and quantized NNUE student.

No pretrained parameters or foreign engine teachers. Values are Black-relative
cp/1000; policy IDs mirror the native engine. Training checkpoints include Adam,
RNG and best validation weights. Only completed epochs are resumed.
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
import struct
import sys

import numpy as np
import shogi
import torch
from torch import nn
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.research.train_nnue import sparse_features, FEATURES
from tools.research.nnue_labels import verified_outcome, source_is_owned_selfplay
from tools.research.postgame_cases import load_archive
from tools.research.nnue_split import position_identity

KING_FEATURES = FEATURES + 2 * 9 * 28 * 81
ACTIONS = 88 * 81 * 2


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def split_root(root, seed):
    # Appending new games must NEVER change an old game's assignment.
    bucket = int(hashlib.sha256(f'{seed}:{root}'.encode()).hexdigest()[:8], 16) % 100
    return 'test' if bucket < 10 else 'validation' if bucket < 20 else 'train'


def features(sfen):
    base = sparse_features(sfen)
    pieces = [f for f in base if f < 28 * 81]
    result = list(base)
    for side in range(2):
        king = next((f % 81 for f in pieces if f // 81 == side * 14 + 7), None)
        if king is None:
            continue
        bucket = (king // 9 // 3) * 3 + king % 9 // 3
        for piece in pieces:
            result.append(FEATURES + (side * 9 + bucket) * 28 * 81 + piece)
    return sorted(result)


def action_id(move):
    if len(move) not in (4, 5):
        raise ValueError('invalid USI action')
    def square(token):
        if token[0] not in '123456789' or token[1] not in 'abcdefghi':
            raise ValueError('invalid square')
        return (int(token[0]) - 1) * 9 + ord(token[1]) - ord('a')
    source = 81 + 'PLNSBRG'.index(move[0]) if move[1] == '*' else square(move[:2])
    if len(move) == 5 and (move[4] != '+' or move[1] == '*'):
        raise ValueError('invalid promotion')
    return (source * 81 + square(move[2:4])) * 2 + (len(move) == 5)


class Network(nn.Module):
    def __init__(self, width=128, residual=0, material_prior=False, correction=False):
        super().__init__()
        self.width, self.residual, self.material_prior = width, residual, material_prior
        self.correction = correction
        if correction and material_prior:
            raise ValueError('correction must not double-count material')
        self.embedding = nn.EmbeddingBag(KING_FEATURES, width, mode='sum')
        self.bias = nn.Parameter(torch.full((width,), .25))
        self.blocks = nn.ModuleList(nn.Sequential(nn.Linear(width, width), nn.ReLU(),
                                                 nn.Linear(width, width)) for _ in range(residual))
        self.value = nn.Linear(width, 1)
        self.policy = nn.Linear(width, ACTIONS)
        nn.init.normal_(self.embedding.weight, std=.015)
        nn.init.normal_(self.value.weight, std=.02)
        nn.init.zeros_(self.value.bias)
        nn.init.normal_(self.policy.weight, std=.01)
        nn.init.zeros_(self.policy.bias)
        if correction:
            nn.init.zeros_(self.value.weight)
        if material_prior:
            # Bootstrap two channels from OUR adopted material model. The
            # remaining nonlinear channels learn positional corrections. This
            # avoids wasting early generations relearning that a rook matters.
            source=(ROOT/'engine/strategy/material.h').read_text()
            def constants(name):
                match=re.search(r'constexpr int '+name+r'\[\] = \{([^}]+)\}',source)
                if not match: raise ValueError('own material constants unavailable')
                return [int(v.strip()) for v in match[1].split(',')]
            base,promoted,hand=map(constants,('base','promoted_values','hand_values'))
            with torch.no_grad():
                self.embedding.weight[:,:2]=0
                self.bias[:2]=0
                self.value.weight.zero_()
                self.value.weight[0,0]=16
                self.value.weight[0,1]=-16
                for side in range(2):
                    for kind in range(1,9):
                        channel=side*14+kind-1
                        self.embedding.weight[channel*81:(channel+1)*81,side]=base[kind]/16000
                        if kind<=6:
                            channel=side*14+kind+7
                            self.embedding.weight[channel*81:(channel+1)*81,side]=promoted[kind]/16000
                    for kind in range(7):
                        at=28*81+(side*7+kind)*18
                        self.embedding.weight[at:at+18,side]=hand[kind+1]/16000
                for block in self.blocks:
                    block[-1].weight.zero_()
                    block[-1].bias.zero_()
            # These own-material channels are a fixed starting prior. All
            # other embeddings/heads (millions of weights) remain trainable.
            def keep_prior(gradient):
                result=gradient.clone()
                result[...,:2]=0
                return result
            self.embedding.weight.register_hook(keep_prior)
            self.value.weight.register_hook(keep_prior)
            self.bias.register_hook(keep_prior)

    def forward(self, ids, offsets, unbounded=False):
        hidden = (self.embedding(ids, offsets) + self.bias).clamp(0, 4)
        for block in self.blocks:
            hidden = (hidden + .25 * block(hidden)).clamp(0, 4)
        value = self.value(hidden).squeeze(-1)
        return (value.clamp(-.6, .6) if self.correction and not unbounded else value), self.policy(hidden)


def tensors(rows, device):
    lens = [len(row['features']) for row in rows]
    return (torch.tensor([f for row in rows for f in row['features']], device=device),
            torch.tensor(np.cumsum([0] + lens[:-1]), device=device, dtype=torch.long))


def policy_loss(logits, rows):
    # Normalize over ALL legal actions; only searched/actually played targets
    # carry positive mass. Absent targets contribute zero policy loss.
    terms = []
    for i, row in enumerate(rows):
        if not row.get('policy') or row.get('policy_weight', .2) == 0:
            continue
        legal = row['legal']
        logp = F.log_softmax(logits[i, legal], dim=0)
        targets = row['policy']
        term = sum(-float(p) * logp[legal.index(int(action))] for action, p in targets.items())
        terms.append(term * row.get('policy_weight', .2))
    return sum(terms) / max(1, len(rows))


def replay_batches(rows, batch_size=128):
    """Replay scarce long-study targets without letting one game fill a batch."""
    focused={}
    ordinary=[]
    for row in rows:
        if row.get('origin') in ('own_deep_search','own_mcts'):
            focused.setdefault(row['root'],[]).append(row)
        else:
            ordinary.append(row)
    if not ordinary:
        ordinary=list(rows)
        focused={}
    roots=sorted(focused)
    quota=min(16,len(roots),batch_size//4)
    order=torch.randperm(len(ordinary)).tolist()
    for start in range(0,len(order),batch_size-quota):
        batch=[ordinary[i] for i in order[start:start+batch_size-quota]]
        for index in torch.randperm(len(roots)).tolist()[:quota]:
            choices=focused[roots[index]]
            batch.append(choices[int(torch.randint(len(choices),(1,)))])
        yield batch


def prepare(archives, seed, per_game=64, extra=None, research_validation=None):
    rows, games = [], []
    for directory in archives:
        source = load_archive(Path(directory))
        if not source_is_owned_selfplay(Path(directory), source):
            raise ValueError('unapproved teacher source')
        games.extend(source)
    identities = [g.row['game_id'] for g in games]
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate source games')
    for game in games:
        outcome = verified_outcome(game)
        if outcome is None:
            continue
        board = shogi.Board(game.start_sfen)
        n = len(game.moves)
        chosen = {min(n-1, k*n//per_game) for k in range(per_game)}
        for ply, move in enumerate(game.moves):
            if ply in chosen and ply >= 8:
                search = game.row['moves'][ply].get('search', {})
                exact = (search.get('score_status') == 'recorded'
                         and type(search.get('score_cp_stm')) is int
                         and not search.get('score_lowerbound') and not search.get('score_upperbound')
                         and search.get('depth', 0) > 0)
                target = outcome * .8
                if exact:
                    cp = search['score_cp_stm'] * (1 if board.turn == shogi.BLACK else -1)
                    target = .85 * np.clip(cp/1000, -6, 6) + .15 * outcome * .8
                row = dict(root=game.row['game_id'], sfen=board.sfen(),
                           target=float(target), weight=1.0 if exact else .3,
                           origin='own_played_search_and_outcome' if exact else 'own_outcome',
                           archive_sha256=game.archive_sha256,
                           policy={str(action_id(move)): 1.0} if exact else {}, policy_weight=.15)
                rows.append(row)
            board.push_usi(move)
    if extra:
        for row in extra:
            if row['root'] not in set(identities) or split_root(row['root'], seed) != 'train':
                raise ValueError('reanalysis may only inherit a training original game')
            if row.get('origin') not in ('own_deep_search', 'own_mcts'):
                raise ValueError('unapproved research label')
            rows.append(dict(row))
    for row in research_validation or []:
        if row['root'] not in set(identities) or split_root(row['root'], seed) != 'validation':
            raise ValueError('research validation must retain a validation original game')
        if row.get('origin') != 'own_deep_search':
            raise ValueError('research validation needs a verified deep-search label')
        rows.append(dict(row))
    position_splits = {}
    for row in rows:
        row['split'] = split_root(row['root'], seed)
        key = position_identity(row['sfen'])
        position_splits.setdefault(key, set()).add(row['split'])
    # Remove cross-split collisions from ALL partitions. Cumulative archives
    # retain old collisions, so later generations cannot resurrect leaked tests.
    rows = [r for r in rows if len(position_splits[position_identity(r['sfen'])]) == 1]
    for row in rows:
        board = shogi.Board(row['sfen'])
        row['features'] = features(row['sfen'])
        row['legal'] = sorted(action_id(m.usi()) for m in board.legal_moves)
        if set(map(int, row.get('policy', {}))) - set(row['legal']):
            raise ValueError('illegal policy target')
        if row.get('policy') and not math.isclose(sum(row['policy'].values()), 1.0, abs_tol=1e-5):
            raise ValueError('policy target not normalized')
    parts = {split: [r for r in rows if r['split'] == split] for split in ('train', 'validation', 'test')}
    if not all(parts.values()):
        raise ValueError('need nonempty independent original-game partitions')
    return rows, parts, games


def save_torch(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    torch.save(value, temp)
    temp.replace(path)


def load_network(path, device='cpu'):
    state = torch.load(path, map_location=device, weights_only=True)
    net = Network(**state['architecture']).to(device)
    net.load_state_dict(state['model'])
    net.eval()
    return net


@torch.no_grad()
def error(net, rows, device='cpu'):
    total = 0
    for start in range(0, len(rows), 128):
        batch = rows[start:start+128]
        value, _ = net(*tensors(batch, device))
        total += (value - torch.tensor([r['target'] for r in batch], device=device)).abs().sum().item()
    return total * 1000 / len(rows)


def selection_metrics(net, rows, device='cpu'):
    ordinary = [r for r in rows if r.get('origin') not in ('own_deep_search', 'own_mcts')]
    research = [r for r in rows if r.get('origin') == 'own_deep_search']
    a = error(net, ordinary, device) if ordinary else None
    b = error(net, research, device) if research else None
    return dict(ordinary_mae_cp=a, research_mae_cp=b,
                score_cp=(a+b)/2 if a is not None and b is not None else a if a is not None else b)


def train(parts, output, width=128, residual=0, epochs=20, seed=20261021,
          warmstart=None, device='cpu', threads=2, correction=False):
    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    architecture = dict(width=width, residual=residual, material_prior=not correction)
    if correction:
        architecture['correction'] = True
    identity = hashlib.sha256(json.dumps({'architecture': architecture,
        'data': {s: [{k:v for k,v in r.items() if k not in ('features','legal')}
                    for r in rows] for s, rows in parts.items()}, 'epochs': epochs,
        'seed': seed, 'implementation_sha256':digest(__file__),
        'warmstart': digest(warmstart) if warmstart else None},
        sort_keys=True).encode()).hexdigest()
    net = Network(**architecture).to(device)
    if warmstart:
        state = torch.load(warmstart, map_location=device, weights_only=True)
        if state['architecture'] != architecture:
            raise ValueError('warm-start architecture changed')
        net.load_state_dict(state['model'])
    # Weight decay would silently modify the supposedly fixed material prior.
    optimizer = torch.optim.AdamW(net.parameters(), lr=.001, weight_decay=0)
    initial_selection = selection_metrics(net, parts['validation'], device)
    best, best_error, start, history = copy.deepcopy(net.state_dict()), initial_selection['score_cp'], 0, []
    initial_error = error(net, parts['validation'], device)
    checkpoint = output / 'resume.pt'
    if checkpoint.exists():
        state = torch.load(checkpoint, map_location=device, weights_only=True)
        if state['identity'] != identity:
            raise ValueError('training resume inputs changed')
        net.load_state_dict(state['model'])
        optimizer.load_state_dict(state['optimizer'])
        torch.set_rng_state(state['rng'].cpu())
        best, best_error, start, history = state['best'], state['best_error'], state['epoch'], state['history']
    for epoch in range(start, epochs):
        net.train()
        running, seen, replayed = 0, 0, 0
        for batch in replay_batches(parts['train']):
            prediction, logits = net(*tensors(batch, device), unbounded=correction)
            target = torch.tensor([r['target'] for r in batch], device=device)
            weight = torch.tensor([r['weight'] for r in batch], device=device)
            loss = (F.smooth_l1_loss(prediction, target, reduction='none')*weight).sum()/weight.sum()
            loss = loss + policy_loss(logits, batch)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 2.0)
            optimizer.step()
            running += loss.item() * len(batch)
            seen += len(batch)
            replayed += sum(r.get('origin') in ('own_deep_search','own_mcts') for r in batch)
        net.eval()
        validation = error(net, parts['validation'], device)
        metrics = selection_metrics(net, parts['validation'], device)
        history.append(dict(epoch=epoch+1, loss=running/seen, validation_mae_cp=validation, selection=metrics,
                            examples_seen=seen,replayed_research_examples=replayed))
        if metrics['score_cp'] < best_error:
            best_error, best = metrics['score_cp'], copy.deepcopy(net.state_dict())
        save_torch(checkpoint, dict(identity=identity, architecture=architecture,
            model=net.state_dict(), optimizer=optimizer.state_dict(), rng=torch.get_rng_state(),
            best=best, best_error=best_error, epoch=epoch+1, history=history))
        print(json.dumps(dict(network='teacher' if residual else 'student', **history[-1])), flush=True)
    net.load_state_dict(best)
    save_torch(output/'model.pt', dict(architecture=architecture, model=net.state_dict()))
    report = dict(schema='own-policy-value-training-v1', identity=identity,
        architecture=architecture, epochs=epochs, initial_validation_mae_cp=initial_error,
        validation_mae_cp=error(net, parts['validation'], device),
        selection=selection_metrics(net, parts['validation'], device), initial_selection=initial_selection,
        correction_training='unbounded_loss_projected_target' if correction else None,
        test_mae_cp=error(net, parts['test'], device),
        sample_counts={s:len(r) for s,r in parts.items()}, history=history,
        model_sha256=digest(output/'model.pt'), strength_proven=False)
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return net, report


def export_nnue(net, path):
    if net.residual:
        raise ValueError('research residual network must be distilled, cannot be deployed as NNUE')
    def quant(tensor, scale, dtype):
        data = np.rint(tensor.detach().cpu().numpy()*scale)
        limits = np.iinfo(dtype)
        if not np.isfinite(data).all() or data.min() < limits.min or data.max() > limits.max:
            raise ValueError('quantization overflow')
        return data.astype(dtype).tobytes()
    blob = (b'KMNNUE04' if net.correction else b'KMNNUE03') + struct.pack('<II', net.width, KING_FEATURES)
    blob += quant(net.bias,256,'<i4') + quant(net.embedding.weight,256,'<i2')
    blob += quant(net.value.weight,256,'<i2') + quant(net.value.bias,65536,'<i4')
    blob += quant(net.policy.weight,256,'<i2') + quant(net.policy.bias,65536,'<i4')
    path = Path(path)
    temp = path.with_suffix('.part')
    temp.write_bytes(blob)
    temp.replace(path)
    return digest(path)


def quantized_cp(path, sfen):
    blob = Path(path).read_bytes()
    magic, width, count = struct.unpack_from('<8sII', blob)
    if magic not in (b'KMNNUE03', b'KMNNUE04') or count != KING_FEATURES:
        raise ValueError('invalid own model')
    bias = np.frombuffer(blob, '<i4', width, 16).astype(np.int64)
    offset = 16 + width*4
    embedding = np.frombuffer(blob, '<i2', count*width, offset).reshape(count,width)
    offset += count*width*2
    head = np.frombuffer(blob, '<i2', width, offset).astype(np.int64)
    out = struct.unpack_from('<i', blob, offset+width*2)[0]
    total = int(np.dot(np.clip(bias+embedding[features(sfen)].sum(axis=0),0,1024),head))+out
    # C++ lround rounds halfway away from zero (Python round uses ties-to-even).
    cp = math.floor(abs(total)*1000/65536+.5) * (1 if total>=0 else -1)
    limit = 600 if magic == b'KMNNUE04' else 30000
    return max(-limit,min(limit,cp))
