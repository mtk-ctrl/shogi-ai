# 雲路 KUMOJI

**雲路（くもじ / KUMOJI）**は、既存の強い将棋AIの答えをできるだけ教師にせず、自分の評価・探索・自己対局経験から強さを育てる自作将棋AIである。

「雲路」は、雲の中の道、空に通う道を表す古い日本語から取った。既に敷かれた道をなぞるのではなく、まだ道に見えないところから、自分で通れる筋を見つけるAIを目指す。

最新のAndroid / OEX完成版（release）は **v1.0.1**（2026-10-05）である。
ただし、その後も `main` のEngine開発は継続しており、200ms正式比較条件とAdaptiveLongThink正式採用など、v1.0.1完成版化後の採用変更が入っている。
したがって **v1.0.1やv0.0.19を現在のmain Engine全体の版番号として扱わない**。現在のEngine状態は `main` のcommitを正本とし、正式比較の基準commitは `benchmarks/baseline_ref.txt` を参照する。

## AI作業時の入口

このリポジトリで開発・調査・対局を行うAIは、最初に [開発ルーター](docs/00_開発ルーター.md) を読む。
現行の運用Ruleは `docs/rules/` のactive文書だけを正本とし、journal・decision・archive・未マージPR・研究ブランチを日時の新しさだけで現行扱いしない。

## 羅針盤

このプロジェクトでは、やねうら王その他の外部AIを**先生ではなく物差し**として扱う。

強化は原則として、Engine / Experience / Benchmark / Diagnosis の役割を分け、Strength / Independence / Novelty を意識して進める。
詳しくは [雲路の羅針盤](docs/00_羅針盤.md) を参照する。

## 現在のmain Engineの主な能力

- やねうら王から利用するのは、合法手生成・局面管理・王手判定・千日手等のルール層のみ
- 探索・評価・move ordering・置換表・詰み探索・戦略・学習は自作
- 可変深度αβ探索、反復深化、時間管理
- AdaptiveLongThink
- 静止探索
- 自作置換表
- 1～3手の攻守MateAssistを通常対局へ統合
- 専用`go mate`による詰み探索
- 駒得＋玉安全＋攻撃圧力＋活動性＋危険度の説明可能な評価
- 自前棋譜から作るOpening Book
- Experience Cache
- 評価値・読み筋・探索統計のUSI出力
- ShogiDroid2向けAndroid OEX APK

評価の現行重みは `Safety=50 / Pressure=150 / Activity=150 / Danger=200`。
正式比較・スクリーニング・Diagnosis・外部Benchmarkの現行条件は [R20](docs/rules/R20_対局・比較・統計.md) を正本とする。

## Book / Experience

Opening BookとExperience Cacheの実装は存在する。
ただし、今後の役割分担、永続化、外部対局由来Experience、自動更新・自動昇格等は現在検討中である。
結論が出るまでは [H10 Book・Experience方針保留](docs/hold/H10_Book・Experience方針保留.md) を参照し、既存実装だけから今後の方針を推定しない。

## 外部対局 / Floodgate

外部棋力を継続的に測るため、やねうら王Material BenchmarkとFloodgate接続基盤を持つ。
外部AIは教師ではなく物差しとして扱い、相手の評価値・PV・候補手を雲路の学習教師にはしない。
詳細な現行Ruleは [R50](docs/rules/R50_外部AI・梯子・Floodgate.md) を参照する。

## Android / ShogiDroid2

最後に完成版化したv1.0.1のAndroid版は次の構成である。mainの未release変更とは区別する。

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
- [24_多面的評価システム構想](docs/24_多面的評価システム構想.md) — 今後の評価システムの方向
- [Book・Experience保留](docs/hold/H10_Book・Experience方針保留.md)
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
