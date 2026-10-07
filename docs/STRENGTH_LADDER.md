# 雲路 強さの梯子（YaneuraOu cross-edition ladder）

## 目的

雲路の成長を、やねうら王を基準に長期で連続して測る。

単に「MATERIAL 1..100」「KPPT 1..100」を別々に測るのではなく、
各評価関数版の強さの段差を直接対局で校正し、版をまたいだ一本の梯子として扱う。

## 名前

自作将棋AIの名称は **雲路（くもじ）**。
開発史・journal・benchmark・結果報告ではこの名称を一貫して使用する。

## 1. 共通レベル尺度

レベル1..100は、評価関数ごとに意味を変えない。

- L1 = 10 nodes / move
- L100 = 1,000,000 nodes / move
- 中間は対数スケール
- 定義は `benchmarks/external_levels.py`

このレベルは「強さそのもの」ではなく、やねうら王に与える探索量を表す。

したがって同じL50でも、MATERIAL L50とKPPT L50は同じ強さとは限らない。
その差を別途「版間ブリッジ」で測る。

## 2. 版ごとの梯子

当面の順序は次のとおり。

1. YaneuraOu MATERIAL
2. YaneuraOu KPPT（Apery WCSC26を固定基準にする）
3. 軽量NNUE
4. 標準NNUE
5. より強いNNUE
6. 外部レーティング（Floodgate等）

新しい版へ進むときは、前後の版を必ず直接対局させて重なりを測る。

## 3. 版間ブリッジ

例：

- KPPT L1 ≒ MATERIAL Lx
- KPPT L10 ≒ MATERIAL Ly
- KPPT L50 ≒ MATERIAL Lz

のように、KPPTの固定レベルとMATERIALの複数レベルを直接対局させ、
勝率50%に最も近いMATERIALレベルを「相当レベル」とする。

実装：

- `benchmarks/yaneuraou_bridge_calibration.py`
- `.github/workflows/yaneuraou-edition-bridge.yml`

粗探索は少数局、候補確定後は100局確認を基本とする。
必要なら隣接レベルも100局確認し、50%に近い方を採用する。

## 4. 雲路の現在地

雲路自身は、各版に対して同じ共通レベル尺度で対局する。

表示例：

- 雲路 vX.Y
- MATERIAL 54相当
- KPPT換算：未到達 / KPPT 3相当
- 統一梯子位置：MATERIAL 54

MATERIALとKPPTの重なりが確定した後は、版をまたいだ換算も併記する。

例：

- MATERIAL 100 ≒ KPPT 18
- 雲路がMATERIAL 100を突破
- 同時に「KPPT 18相当地点を突破」と記録できる

## 5. 等時間戦

nodes制の梯子とは別に、実用上の比較として等時間戦も持つ。

例：

- MATERIAL 200ms vs KPPT 200ms
- MATERIAL 200ms vs NNUE 200ms

これは「同じ実時間・同じCPUでどちらが強いか」を測る。
評価関数の重さも含めた実効棋力を見る指標であり、
nodes制の公式梯子とは混ぜない。

## 6. 記録原則

- 版名・評価関数ファイル・YaneuraOu commitを固定して記録する。
- 定跡は原則OFF。
- Threads=1。
- CPU型番を記録する。
- 先後は均衡させる。
- 勝率だけでなく95%区間を残す。
- 版間換算は直接対局を優先し、雲路を共通アンカーにした換算は暫定値として扱う。
- 新しい評価版を追加する場合は、直前の版とのブリッジを作ってから梯子へ追加する。
