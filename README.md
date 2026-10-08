# 雲路 KUMOJI

**雲路（くもじ / KUMOJI）**は、既存の強い将棋AIの答えをできるだけ教師にせず、自分の評価・探索・自己対局経験から強さを育てる自作将棋AIである。

「雲路」は、雲の中の道、空に通う道を表す古い日本語から取った。既に敷かれた道をなぞるのではなく、まだ道に見えないところから、自分で通れる筋を見つけるAIを目指す。

現在の正式Engine世代は **KUMOJI v2.0.3** である。Evaluation-v2候補Bとv2.0.1の長考配分、採用済み局面知識の毎対局利用を維持し、旧Book / Experienceの実行機能とUSI設定を現行エンジンから除去した。採用済み実装は `main` を正本とする。
最後にAndroidへ配布するために作ったAPKは **v1.0.1**（2026-10-05）である。v2以後はAndroidへダウンロードする必要がなくAPKを新たに作っていないため、オーナーのAndroidには以前のv1が入っている（2026-10-07本人確認）。APKは必要時に採用済みエンジンをAndroidへ届けるものであり、別の正式エンジン系統ではない。
正確な実装状態は `main` のcommit SHAでも特定し、正式比較の基準commitは `benchmarks/baseline_ref.txt` を参照する。

## AI作業時の入口

このリポジトリで開発・調査・対局を行うAIは、最初に [開発ルーター](docs/00_開発ルーター.md) を読む。
現行の運用Ruleは `docs/rules/` のactive文書だけを正本とし、journal・decision・archive・未マージPR・研究ブランチを日時の新しさだけで現行扱いしない。

## 羅針盤

このプロジェクトでは、やねうら王その他の外部AIを**先生ではなく物差し**として扱う。

強化は原則として、Engine / 局面知識 / Benchmark / Diagnosis の役割を分け、Strength / Independence / Novelty を意識して進める。
詳しくは [雲路の羅針盤](docs/00_羅針盤.md) を参照する。

## 現在のmain Engine（KUMOJI v2.0.3）の主な能力

- やねうら王から利用するのは、合法手生成・局面管理・王手判定・千日手等のルール層のみ
- 探索・評価・move ordering・置換表・詰み探索・戦略・学習は自作
- 可変深度αβ探索、反復深化、時間管理
- AdaptiveLongThink（不安定な局面を優先し、残り枠は150手程度までに消化）
- 静止探索
- 自作置換表
- 1～3手の攻守MateAssistを通常対局へ統合
- 専用`go mate`による詰み探索
- Evaluation-v2候補Bによる多面的静的評価（Material / Safety / Pressure / Activity / Danger / Influence / Potential / Coordination / Hand Potential。Threatは現行OFF）
- 採用済み局面知識（探索開始時の読み順へ反映し、通常対局で毎回利用）
- 評価値・読み筋・探索統計のUSI出力
- ShogiDroid2向けAndroid OEX APK

評価の現行既定値は `EvalV2=true / Material=100 / Safety=500 / Pressure=474 / Activity=150 / Danger=200 / Influence=19 / Potential=25 / Coordination=50 / HandPotential=60 / Threat=0 / PositionalCap=5000`。
正式比較・スクリーニング・Diagnosis・外部Benchmarkの現行条件は [R20](docs/rules/R20_対局・比較・統計.md) を正本とする。

## 局面知識

今後は「対局記録・研究記録・局面知識」の構成で進める（2026-10-07本人承認）。原本を出所付きで蓄積し、現在の雲路が対局で使う情報を小さな局面知識へまとめる。定跡はそのうち序盤の手順・分岐を整理した部分である。
保存と次回対局へ過去の手を優先して読む形で渡す接続仕様は [局面知識の統合設計と即活用](docs/35_局面知識の統合設計と即活用.md) を参照する。新しい対局記録から知識候補を自動生成する処理は未実装。
外部AI対局でも、雲路自身が読んだ手・評価は局面知識の候補に含める（2026-10-08本人確認、出所境界の正本はR50）。新しい局面知識の正式採用・自動更新や、研究結論を直接着手へ使う方式は、別途検証と採用判断を行う。

## 外部対局 / Floodgate

外部棋力を継続的に測るため、やねうら王Material BenchmarkとFloodgate接続基盤を持つ。
外部AIは教師ではなく物差しとして扱い、相手の評価値・PV・候補手を雲路の学習教師にはしない。
人間との対局を学習に使う対象はオーナー本人との対局だけとする（2026-10-07本人確認）。他の人の棋譜を学習へ取り込まない。
詳細な現行Ruleは [R50](docs/rules/R50_外部AI・梯子・Floodgate.md) を参照する。

## Android / ShogiDroid2

最後に作ったv1.0.1 APKは次の構成である。最新エンジンv2.0.3を含むAPKはまだ作っていない。

- アプリ表示名：`雲路 KUMOJI`
- OEX表示名：`雲路 KUMOJI v1.0.1`
- USI名：`KUMOJI v1.0.1`
- Application ID：`com.mtkctrl.shogiai`
- native engine：`libshogiai.so`
- CPU：`arm64-v8a`
- versionName：`1.0.1`
- versionCode：`10101`

Application ID、nativeファイル名、固定開発署名は旧版との更新互換性のため維持している。
APK・実機確認・完成版化のRuleは [R60](docs/rules/R60_Android・APK・リリース.md) を参照する。

## 正本

このリポジトリ `mtk-ctrl/shogi-ai` を唯一の正本とする。
ソフト名は雲路へ変わったが、リポジトリ名や一部の内部ファイル名は開発史・互換性・自動化を壊さないため当面維持する。

## 主な資料

- [00_開発ルーター](docs/00_開発ルーター.md) — AIが作業前に読む入口
- [00_羅針盤](docs/00_羅針盤.md) — 何を目指すか
- [Rules](docs/rules/R00_基本原則.md) — 現在どうするか
- [04_強化ロードマップ](docs/04_強化ロードマップ.md) — 技術フェーズと到達点
- [32_評価関数v2統合設計](docs/32_評価関数v2統合設計.md) — v2評価アーキテクチャ
- [33_v2.0.0世代基準](docs/33_v2.0.0世代基準.md) — 評価プロファイルBとv2.0.0採用時の棋力測定
- [36_v2.0.1長考配分](docs/36_v2.0.1長考配分.md) — 現行版の長考配分と検証
- [24_多面的評価システム構想](docs/24_多面的評価システム構想.md) — 今後の評価システムの方向
- [v1.0.1完成版記録](journal/2026-10-05_18_雲路KUMOJI_v1.0.1完成版.md)
- [CHANGELOG](journal/CHANGELOG.md)

## ビルド

ホスト版：

```bash
python3 scripts/build.py --output build/shogi-ai
```

主要な短時間検証はGitHub Actionsの `Quick Strategy CI`、Android完成版は `Build Android OEX APK` で行う。
`android/VERSION` の変更を完成版APK生成の明示的な合図とする。

## 開発上の境界

外部AIを使って強さを測ることはためらわない。しかし、外部AIの考え方へ引っ張られないことを、このプロジェクトの独立性として大切にする。

最終的な夢は、既存AIや既存定跡からは生まれにくい指し回しを、自分自身の探索と経験から見つけ、それでも強い将棋AIになることである。
