# 自己対局→学習→候補エンジンの接続

正式採用とは分離した研究用の1世代サイクル。自作の通常評価へ、実際の自己対局勝敗で学んだ小型ネットワークの補正を加える。通常評価の計算済み情報を使い、追加の盤面走査をしない。候補は既定OFFで、採用・main更新は自動化しない。

## 再実行

1. 現行ルーターと必要なRuleを読む。空きrunnerを確認し、既存 `engine-match.yml` で同じ固定候補同士を対局させる。初回は `collection-request.json`、Issue #270、本体run 38853046638、19laneの1000局。正式v2.0.20同士で、知識・長考・先読み・初手非香ランダムを双方有効にする。次世代で学習モデルを有効にする場合も双方同条件で固定し、通常の受付制限に従う。
2. 全shard・aggregate・played archive・manifestを取得し、build jobの実際のcheckout SHAと出力バイナリSHAを確認する。初回の `collection-build-provenance.json` が例。generic workflowは別ディレクトリで2本をビルドするため実体hashは異なる。初回は同じsource commitに加え、双方のELF `.text` のSHA256も一致した。同一バイナリと偽装して旧NN収集器へ投入せず、このサイクルで出所を区別する。
3. 標準形式の原本を `build/runs/RUN_ID/` へ置き、以下を実行する。これにより合法性・出所・分割/重複検査、学習、モデルの固定出力、候補の埋込ビルド、OFF一致/推論/USI検査まで再現できる。検証用誤差が従来以下でない場合はモデルと報告を保存し、候補ビルドへ進めない。

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 research/selfplay-learning-20261016/run_cycle.py \
  --archive-dir build/runs/38853046638 \
  --provenance research/selfplay-learning-20261016/collection-build-provenance.json \
  --baseline /absolute/path/to/pinned-v2020 \
  --output-dir build/selfplay-cycle --build-candidate
```

4. 別の48局面の固定深さ/200ms診断で計算負担を測り、PLANの条件を通れば、モデル・コードを研究branchのcommitで固定して既存の汎用内部比較を200局行う。Aだけ `SelfPlayEval=true`、Bは正式版、双方同じ知識とR20の条件にする。勝敗を見る前にモデルを固定し、違法手・先読み・長考・時間・知識・source/binary hashを監査する。
5. 次世代も、採否と切り分けて同じ仕組みを使える。学習・検証・最後の試験はshard/棋譜単位に分ける。勝者の手を全て正解とせず、未知局面での勝敗予測と未使用seedの実戦成績を区別する。

## 出力と保存

`samples.manifest.json` は出所・除外/重複・分割数・知識・合法着手数、`training-report.json` は学習候補・選定epoch・検証/試験誤差・対局単位の誤差差95%区間、`model.txt` と生成headerは固定モデル、`cycle-result.json` は処理の到達点を記録する。モデルの補正上限は最大600点、最終静的評価は従来の上限で制限する。詰み/反復のルール点を補正しない。

データ原本のartifactは90日保存を要求する一時受渡しであり、永続保存とは呼ばない。大量の原棋譜・学習局面をソースへcommitしない。継続利用するモデルと小さい検証報告・manifest・出所は研究branchへ保存し、元の実戦原本はR25の期限と移送状況を明示する。未着手候補・PV・探索木を学習用の長期記録へ追加しない。

`tests/test_selfplay_learning.py` が数値一致・汎化/再現性・先後反転・分割漏洩・終局教師の検査、`tests/test_selfplay_eval_usi.py` が補正OFF/0の完全一致・補正ON合法性・C++推論・欠損/復旧・material診断、追加引数付き `tests/search_test.cpp` が学習評価込み独立minimaxを確認する。数値用の合成fixtureと、実対局から学んだモデルは区別する。
