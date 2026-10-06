# King Defense Network 初期検証

二重King Zone（距離1/距離2）と8方向ごとの敵到達度で、守備連携を機械判定する研究用Challenger。囲い名は使用しない。

## 固定局面
```
PASS same-material king shelter 1225 > 1216
PASS real pressure and no king-proximity bonus
PASS king defence relevant flank 18 > 0
PASS two-ring urgency inner 30 > outer 18
PASS supported guard network 24 > scattered 0
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
- Challenger: 7勝 / Baseline: 9勝 / 引分: 0
- Challenger得点率: 0.438
- 平均応答: A 188.2ms / B 187.2ms

## 200ms / Book ON / 30局
- Challenger: 9勝 / Baseline: 21勝 / 引分: 0
- Challenger得点率: 0.300
- 平均応答: A 167.1ms / B 164.8ms

## 扱い
固定局面は機械判定の妥当性確認、対局は初期シグナル。30局だけで本採用は決めない。
