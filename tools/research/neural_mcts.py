#!/usr/bin/env python3
"""Own PUCT research search. Native rules adjudicate each full move history.

Only root visit/value distributions are retained; no persistent all-node tree.
Network parameters come exclusively from our verified selfplay trainer.
"""
from dataclasses import dataclass, field
import math
from pathlib import Path
import queue
import subprocess
import threading

import shogi
import torch
from tools.research.neural_model import action_id, features, tensors


class RulesOracle:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(Path(binary).resolve())], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.lines = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.lines.put(line.rstrip())
            self.lines.put(None)
        self.thread = threading.Thread(target=read, daemon=True)
        self.thread.start()

    def state(self, start_sfen, history):
        command = 'position sfen '+start_sfen + (' moves '+' '.join(history) if history else '')
        if '\n' in command or '\r' in command:
            raise ValueError('invalid rule request')
        self.process.stdin.write(command+'\nrules\n')
        self.process.stdin.flush()
        while True:
            line = self.lines.get(timeout=15)
            if line is None:
                raise RuntimeError('native rules process exited')
            if 'invalid position' in line or 'rules error' in line:
                raise ValueError(line)
            if line.startswith('info string rules result '):
                parts = line.split()
                index = parts.index('moves')
                fields = dict(zip(parts[3:index:2],parts[4:index:2]))
                return dict(result=int(fields['result']), turn=int(fields['turn']),
                            declare=bool(int(fields['declare'])), moves=parts[index+1:])

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('quit\n')
                self.process.stdin.flush()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=3)
        self.thread.join(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()


@dataclass
class Node:
    prior: float = 1.0
    visits: int = 0
    total: float = 0.0  # side-to-move-relative at THIS node
    expanded: bool = False
    terminal: float | None = None
    children: dict = field(default_factory=dict)


def terminal_value(state):
    if state['result'] == 1:
        return 0.0
    if state['result'] in (2,3):
        winner = state['result'] - 2
        return 1.0 if winner == state['turn'] else -1.0
    if state['declare']:
        return 1.0
    return None


@torch.no_grad()
def research(net, oracle, start_sfen, history, simulations=256, cpuct=1.5,
             max_depth=128, on_progress=None):
    if not 2 <= simulations <= 1000000 or not 1 <= max_depth <= 256:
        raise ValueError('invalid bounded MCTS budget')
    root = Node()
    root_board = shogi.Board(start_sfen)
    for move in history:
        root_board.push_usi(move)
    def expand(node, board, path):
        state = oracle.state(start_sfen, path)
        if state['turn'] != board.turn:
            raise ValueError('rules/network orientation differs')
        node.expanded = True
        node.terminal = terminal_value(state)
        if node.terminal is not None:
            return node.terminal
        moves = state['moves']
        if not moves:
            raise ValueError('ongoing position without legal moves')
        ids = [action_id(m) for m in moves]
        value, logits = net(*tensors([{'features':features(board.sfen())}],next(net.parameters()).device))
        probabilities = torch.softmax(logits[0,ids],0).cpu().tolist()
        node.children = {move:Node(prior=p) for move,p in zip(moves,probabilities)}
        return math.tanh(float(value.item())*1000/600) * (1 if board.turn==shogi.BLACK else -1)
    expand(root,root_board,list(history))
    if root.terminal is not None:
        raise ValueError('cannot generate policy label for terminal root')
    for simulation in range(simulations):
        board = shogi.Board(root_board.sfen())
        path, nodes, node = list(history), [root], root
        for depth in range(max_depth):
            if node.terminal is not None:
                value=node.terminal
                break
            if not node.expanded:
                value=expand(node,board,path)
                break
            move, child = max(sorted(node.children.items()),key=lambda pair:
                (-pair[1].total/pair[1].visits if pair[1].visits else 0.0)
                + cpuct*pair[1].prior*math.sqrt(node.visits+1)/(1+pair[1].visits))
            board.push_usi(move)
            path.append(move)
            node=child
            nodes.append(node)
        else:
            # Bounded depth is an evaluation, never a forced draw/terminal label.
            if not node.expanded:
                value=expand(node,board,path)
            elif node.terminal is not None:
                value=node.terminal
            else:
                v,_=net(*tensors([{'features':features(board.sfen())}],next(net.parameters()).device))
                value=math.tanh(float(v.item())*1000/600)*(1 if board.turn==shogi.BLACK else -1)
        for visited in reversed(nodes):
            visited.visits+=1
            visited.total+=value
            value=-value
        if on_progress and (simulation+1)%32==0:
            on_progress({'completed_simulations':simulation+1,
                         'root_visits':{m:c.visits for m,c in root.children.items()}})
    counts={m:c.visits for m,c in root.children.items()}
    total=sum(counts.values())
    return dict(bestmove=max(sorted(counts),key=counts.get), completed_simulations=simulations,
        root_visits=counts, policy={str(action_id(m)):n/total for m,n in counts.items() if n},
        value_black=root.total/root.visits*(1 if root_board.turn==shogi.BLACK else -1),
        teacher_status='own_search_uncertain', full_history=True)
