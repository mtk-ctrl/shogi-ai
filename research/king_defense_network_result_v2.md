# King Defense Network 再検証（monotonic risk）

二重King Zone（距離1/距離2）と8方向ごとの敵到達度で、守備連携を機械判定する研究用Challenger。囲い名は使用しない。

## 固定局面
```
PASS same-material king shelter 1225 > 1216
PASS real pressure and no king-proximity bonus
PASS king defence relevant flank risk 0 < 27
PASS two-ring urgency risk inner 45 > outer 27
PASS supported guard network risk 0 < scattered 27
PASS removing pressure never loses defence value
PASS king defence color symmetry
PASS active rook/bishop rays and idle pieces
PASS hanging high-value piece, equal exchange, cheap attacker
PASS every piece/promotion geometry, blockers and king-vacated xray
PASS 180 legal positions color/turn symmetry and bounded integer terms
PASS mate/poisoned pawn/TT evaluator isolation/repetition rollback
PASS silver/knight/lance nonpromotion retained
PASS both opponent pawn promotion choices reach search leaves
PASS feature search equals exhaustive three-ply oracle (both turns)
```

## 200ms / Book OFF / 16局
- Challenger: 8勝 / Baseline: 7勝 / 引分: 1
- Challenger得点率: 0.531
- 平均応答: A 188.5ms / B 188.3ms
- 平均手数: 132.6 ply / 終局理由: {'checkmate': 15, 'move_limit': 1}

## 200ms / Book ON / 30局
- Challenger: 15勝 / Baseline: 15勝 / 引分: 0
- Challenger得点率: 0.500
- 平均応答: A 168.3ms / B 168.1ms
- 平均手数: 136.5 ply / 終局理由: {'checkmate': 30}

## 扱い
固定局面は機械判定の妥当性確認、対局は初期シグナル。30局だけで本採用は決めない。
