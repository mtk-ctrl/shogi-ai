# 雲路 M「機動・協調」対 現行正式版 — 600局比較結果（2026-10-10）

## 結論
- **M型が局面知識OFF・ONの両条件で現行正式版に勝ち越した。** ただし採用判断はオーナーに留保する。
- 局面知識ONは双方で153局面の同一資産を正常に読み込んだが、**一致0回**。今回の結果は局面知識による研究手の直接利用を示しておらず、ON/OFF間の勝率差を局面知識の効果とみなせない。
- 2条件で開始乱数（seed）が異なる。統計的な比較には開始局面・乱数の統制を改善する余地がある。

## 対局成績
| 条件 | M勝 | 引分 | 現行勝 | M得点率 | GitHub集計の95%近似区間 | M先手の勝-分-負 | M後手の勝-分-負 |
|---|---:|---:|---:|---:|---|---|---|
| OFF | 174 | 5 | 121 | 58.83% | 53.26–64.40% | 96-0-54 | 78-5-67 |
| ON | 175 | 7 | 118 | 59.50% | 53.95–65.05% | 102-3-45 | 73-4-73 |
| 合計 | 349 | 12 | 239 | 59.17% | 約55.3–63.1%（各局の得点の標本分散による参考値） | 198-3-99 | 151-9-140 |

- 各条件300局・10分割×30局、先後150局ずつ。両条件とも違法手0局。
- 平均手数はOFF 125.55手、ON 125.55手。
- Mの得点率はONのほうが0.67ポイント高いが、誤差・seedの差に比べて小さい。因果効果を主張しない。
- 全600局で完全同一の着手列は592種類（OFF内1局分、ON内5局分、両条件間2局分の重複）。重複を考慮せず独立対局とみなした区間は過信しない。
- 12手目までの手順の種類：OFF 236、ON 227。先手側の成績が相対的に高く、開始局面・先後の影響を確認する価値がある。

## 再現条件と正本
- 対局A：研究候補 M、engine ref `64aa9036a1172aaf8f5f4b17b7e78f238f0b3b6c`（玉周囲24マスV2）。
- 対局B：実行時の現行正式版main `b2a88e0afcdd944decbd3e7f41cbddc9cd60c824`。
- GitHub compareで両commit間の差は `.github/match-request.json` のみ。Engineソースの変更差ではなく、USI評価設定の比較である。
- M側の設定：`AdaptiveLongThink=true`、`EvalV2=true`、`EvalPositionalCap=5000`、`EvalMaterialWeight=100`、`EvalSafety=480`、`EvalPressure=380`、`EvalActivity=410`、`EvalDanger=150`、`EvalInfluence=140`、`EvalPotential=210`、`EvalCoordination=340`、`EvalHandPotential=60`、`EvalThreat=20`。
- 現行B側は正式版の既定評価設定。双方 `AdaptiveLongThink=true`。
- OFF：両者 `PositionKnowledge=false`。ON：両者 `PositionKnowledge=true`、同一 `build/position-knowledge-v1.tsv`。
- ONの知識件数153、両者のSHA-256 `234173daefd3d0f8ccb205776b5c71ed8e875b5446b3620196cf91a3067b4b1c`。
- OFFの知識照会 A=0、B=0。一致 A=0、B=0。ONの照会 A=18,317、B=18,380。一致 A=0、B=0。探索順の繰り上げ A=0、B=0。
- `go movetime 200`、AdaptiveLongThinkで必要時に最大1秒、最大300手。
- OFF：seed `2026102010`、run `38013956274`、設定commit `3c86db27fac8fbfc79fc7755cb5bf2b47a12b843`。
- ON：seed `2026103010`、run `38013980802`、設定commit `ef424f4489fa939ebd9a56f13f0513f681f5ee6f`。
- 全20対局ジョブ、2集約ジョブがsuccess。M側実体SHA-256 `5187307984c0836dafe3cb1709d838b0cf37aeab1267dfb266476cf334c3dd1b`、B側 `0eca660c3e2ac506e50ad3141a396140d1e854fc8f6f2031593da4574ca04013`。両条件で同一。
- 長考使用の近似指標（各着手の探索報告時間が200ms超）：OFF A=2,540回、B=2,500回、ON A=2,559回、B=2,562回。これはエンジン内部の正式な長考発動回数と完全同義とは限らない。
- 探索ノード合計：OFF A=454,491,461、B=488,574,493。ON A=389,942,619、B=420,072,051。
- 着手記録：OFF 37,664手（評価欠損1,148）、ON 37,666手（評価欠損1,409）。各10分割のmetadata一致と保存記録のSHA-256を検証。

## 成果物
- OFF実行：https://github.com/mtk-ctrl/shogi-ai/actions/runs/38013956274
- ON実行：https://github.com/mtk-ctrl/shogi-ai/actions/runs/38013980802
- OFF集計artifact ID `11654854588`、着手アーカイブ `11655800714`。
- ON集計artifact ID `11654564987`、着手アーカイブ `11654669808`。
- 2実行とも個別対局artifact 10個・集計・着手記録が揃う。保存期限は2027-01-08（JST）。
- OFF着手圧縮データSHA-256 `1df56be7f51ebc3eb3fbb8b332d7c45970801039d4ae41e0a126d16edfa66a93`。
- ON着手圧縮データSHA-256 `53a13813232f7ea998115167d6cc16c4c14a5f11289dac56ac76df95bc1ad4b1`。

## 判断
M型は有力な評価関数候補である。ただし本比較のみで正式版へ採用しない。特に局面知識ON/OFFの有効性は、実際に登録局面が現れる比較で別途検証する必要がある。ユーザー指示なしに追加対局は起動しない。
