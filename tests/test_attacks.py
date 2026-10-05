"""Independent python-shogi geometric attack oracle, including friendly endpoints."""
import json
import random
import subprocess
import sys
import shogi

rng = random.Random(51010)
positions = []
for game in range(4):
    b = shogi.Board()
    for ply in range(100):
        positions.append(b.sfen())
        legal = list(b.legal_moves)
        if not legal:
            break
        b.push(rng.choice(legal))
        if b.is_game_over():
            break
# Explicit promoted and unpromoted pieces of both colors, with blockers.
# Remote kings are off the central slider rays; all endpoints are compared.
for symbol in ['P','L','N','S','B','R','G','+P','+L','+N','+S','+B','+R']:
    for white in [False, True]:
        for blocked in [False, True]:
            b = shogi.Board(); b.clear()
            pieces = {'9h':'K','1b':'k','5e':symbol.lower() if white else symbol}
            if blocked:
                pieces.update({'5c':'p','5g':'P','3c':'P','7g':'p'})
            for at, piece in pieces.items():
                b.set_piece_at(shogi.SQUARE_NAMES.index(at),shogi.Piece.from_symbol(piece))
            positions.append(b.sfen())

p = subprocess.run([sys.argv[1], '--attacks'], input='\n'.join(positions)+'\n',
                   text=True, capture_output=True, check=True)
rows = [json.loads(line) for line in p.stdout.splitlines()]
assert len(rows) == len(positions)
for sf, row in zip(positions, rows):
    b = shogi.Board(sf)
    expected = [[0]*81 for _ in range(2)]
    for square in shogi.SQUARES:
        piece = b.piece_at(square)
        if not piece:
            continue
        attacks = shogi.Board.attacks_from(piece.piece_type, square, b.occupied, piece.color)
        for target in shogi.SQUARES:
            if attacks & shogi.BB_SQUARES[target]:
                name = shogi.SQUARE_NAMES[target]
                expected[piece.color][(int(name[0])-1)*9+ord(name[1])-ord('a')] += 1
    assert row['attacks'] == expected, (sf, row['attacks'], expected)
print(f'PASS independent geometric attacks: {len(rows)} positions, both colors, all 81 squares')
