# 雲路 NNUE自己対局強化：2026-10-21研究実装

## 状態

本ブランチは **正式Engine KUMOJI v2.0.21ではなく、採否前の研究候補**。添付「雲路の自己対局強化――分析を中心に据えた再設計案・第2版」の第1段階を実装する。従来の9軸評価を前提にしない、配置・駒種・持ち駒・手番の疎な特徴から学ぶ自前のNNUE風モデルであり、外部エンジンの正解や重みは教師にしない。通常エンジンの既定動作は変更しない。

## 実装した範囲

- engine/strategy/nnue_eval.h：疎特徴の整数CPU推論、厳格なモデル形式KMNNUE01、着手前後の特徴差分からのaccumulator更新関数
- engine/strategy/evaluation.h と engine/main.cpp：オプション EvalNeural（既定false）と EvalNeuralFile を明示したとき、探索末端の評価本体をNNUEへ置き換え、欠損モデルならエラー。既存正式評価は変更しない
- tools/research/nnue_deep_study.py：検証済み実着手から対象を抽出し、50ms予備読みに続く10分研究、判断変更時の50分研究、双方の候補の10分ずつの反証探索。研究ケース終了ごとに保存し、中断後再開
- tools/research/nnue_labels.py：既存postgame_casesの完全棋譜・終局検証、通常の自己対局結果の弱いラベルと自前長考の条件付きcp教師を別々に作成する。第三者エンジン対局・欠測・未決着を混ぜない
- tools/research/train_nnue.py：元対局単位で学習・調整・未使用群に分割し、同一局面の漏洩を防止。自前でニューラル重みを学習し整数モデルへ変換。学習誤差では棋力を証明できないことを報告
- tools/research/nnue_cycle.py：原本検証→長考→教師抽出→モデル学習・ハッシュ保存→ネイティブUSIの評価一致／1手探索の動作を接続する研究用CLI。比較対局・世代更新・正式採用はしない
- tests/test_nnue_* と quick-ci.yml：モデル差分一致、外部教師排除、研究履歴、長考予算・中断再開、実戦用評価読込を検査

## 実行の入口

既存Actions等から取り出した、完全検証済み自己対局アーカイブ（同じフォルダ内のplayed-games.jsonl.gzとmanifest.json）、固定した正式親バイナリ、採用済みposition-knowledge-v1.tsvが必要。期限付きActions artifactは長期保存とは扱わない。研究結果をソースリポジトリへ大量commitしない。

研究CLIの例（固定した親commitには40桁の実際のSHAを指定）：

    python3 scripts/build.py --output build/shogi-ai
    python3 -m pip install numpy python-shogi==1.1.1
    python3 tools/research/nnue_cycle.py \
      --archive-dir /path/to/played-archive \
      --engine build/shogi-ai \
      --knowledge position-knowledge-v1.tsv \
      --parent-commit YOUR_40_HEX_COMMIT \
      --output-dir /path/to/research-results \
      --max-cases 4 --medium-ms 600000 --long-ms 3000000 \
      --branch-ms 600000 --hidden 128 --epochs 30

少量の接続確認では medium-ms=1000、long-ms=2000、branch-ms=1000 などの別予算を使用し、長考研究を実施したと誤認しないこと。通常の評価は200ms＋現行の追加長考・先読み・知識を両側で揃える。50分研究に加えて候補両枝を各10分調べたら研究時間は合計70分相当として別途集計する。

研究出力はdeep-study.json（終了局面を再開で再利用）、nnue-labels.jsonl、manifest、candidate.nnue、training.json、status.json。親commit・元原本・知識ファイルのハッシュと学習元局識別子を保持する。モデルは研究候補であり、対局して強くなったことを示さない。

## 2026-10-21 実データでの第1段階接続試験（実施済み）

GitHub Actions run 39570656326（NNUE Real-Source Research Pilot）は成功。GitHub Release records-2026-10-01の2026-10-20 spiral初期自己対局パッケージから、合法手・終局・出所を再検証した100局、11,877着手を復元した。小規模接続確認として1局面を50ms/1,000msで研究、終了後801ラベル（確定済み自己対局結果800、自前研究cp 1）を抽出し、元局100群で分離。訓練641・調整72・未使用テスト78件。隠れ幅16、3epochの接続確認モデルを作り、ネイティブUSIで値一致・深さ1の実探索まで動作確認した。

未使用テストMAE 798.06cp（予測ゼロの比較値800.0cp）という結果は**評価精度がほとんど改善していない**ことを示す。これは小型・短時間の接続確認モデルであり、棋力向上や本来の10分/50分教師品質は示さない。独立対局は未実施、研究親更新0、正式版変更0。成果物は30日期限付きActions artifactのみであり、永続保存を確認したと扱わない。

- 実行・ログ: https://github.com/mtk-ctrl/shogi-ai/actions/runs/39570656326
- 一時研究結果: https://github.com/mtk-ctrl/shogi-ai/actions/runs/39570656326/artifacts/12331961955
- PR: https://github.com/mtk-ctrl/shogi-ai/pull/291

## 未実装・完了ではない範囲

1. NNUE差分accumulatorをαβの各再帰手で維持すること（差分関数とテストのみ。現在は探索末端で盤面を再計算）
2. 保存済み100局の小型短時間接続試験は完了したが、10〜50分研究の実時間実行、十分な学習材料での強いNNUE候補、多世代学習、および月別Releaseへの新モデル・追加研究データ永続保存の実働確認
3. 学習した候補順位、方策・価値ネット、MCTS、別方式間の不一致研究と蒸留
4. 学習候補の独立100〜200局選別、1,000局比較、固定基準との累積棋力比較
5. 親研究モデルの自動昇格と、多世代3サイクルの中断復旧を含む完走

CPU予算10%対局・65%分析・10%学習・15%評価は添付提案の初期案であり、実測した配分ではない。

## 研究の安全境界

- 学習元は自己対局の合法・終局確認済み実戦と自前探索のみ。外部やねうら王は物差しとして利用できるが教師にしない
- 分析結果が長時間読まれた事実だけでは正解とみなさず、評価視点・cp/mate・bound・完了反復・局面履歴・原本SHAを検査。元対局の勝敗を仮想の分岐へ転用しない
- 元対局と派生局を同じ分割群で扱い、未使用検証データを再学習させない
- R25の「長期保存は実着手を基本とし、未着手候補・PV一覧・探索木を蓄積しない」を守る。研究用に選んだ局面の比較値は派生データであり、恒久保存の範囲は別途ルールとの整合が必要
- 検証前の研究親昇格・main Engine更新は禁止し、R10の本人採用判断を保持

対局成功・学習成功・独立棋力改善・研究親更新は異なる判定とし、CI成功だけで開発完了とは扱わない。
