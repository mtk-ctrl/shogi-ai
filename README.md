# 雲路 KUMOJI

**雲路（くもじ / KUMOJI）**は、既存の強い将棋AIの答えをできるだけ教師にせず、自分の評価・探索・自己対局経験から強さを育てる自作将棋AIである。

「雲路」は、雲の中の道、空に通う道を表す古い日本語から取った。既に敷かれた道をなぞるのではなく、まだ道に見えないところから、自分で通れる筋を見つけるAIを目指す。

現在の完成版は **v1.0.1**。戦略・評価・探索の棋力基準は正式採用版v0.0.19であり、直前に検証したv0.0.20探索効率化候補（Killer / History / PVS / Aspiration window）は不採用のため含めていない。

## 羅針盤

このプロジェクトでは、やねうら王その他の外部AIを**先生ではなく物差し**として扱う。

強化は原則として次の順で確かめる。

1. Engine または Experience を変更する
2. Diagnosisで狙いどおり動くか確認する
3. 現行採用版との同条件自己対局で、自分自身を超えたか確認する
4. やねうら王等の外部Benchmarkで、外から見ても通用するか測る
5. Diagnosisで、なぜ強く／弱くなったかを調べる

評価では **Strength / Independence / Novelty** を意識する。奇抜さそのものではなく、独立した考え方から自然に生まれた、既存の常識とは違う強い指し回しを価値あるものとする。

詳しくは [雲路の羅針盤](docs/00_羅針盤.md) を参照する。

## v1.0.1の主な能力

- やねうら王から利用するのは、合法手生成・局面管理・王手判定・千日手等のルール層のみ
- 探索・評価・move ordering・置換表・詰み探索・戦略・学習は自作
- 可変深度αβ探索、反復深化、時間管理
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

## Opening Book

標準Bookは `shogi-ai-book.tsv` で管理する。

PC等では外部TSVを優先して読み込む。Android OEXのようにエンジン実行ファイルだけが渡される環境でも同じBookを利用できるよう、ビルド時に標準Bookをエンジンへ内蔵し、標準ファイルが見つからない場合だけフォールバックする。

外部AIとの対局棋譜・推奨手・PV・評価値をBookの教師には使用しない。

## Android / ShogiDroid2

v1.0.1のAndroid版は次の構成である。

- アプリ表示名：`雲路 KUMOJI`
- OEX表示名：`雲路 KUMOJI v1.0.1`
- USI名：`KUMOJI v1.0.1`
- Application ID：`com.mtkctrl.shogiai`
- native engine：`libshogiai.so`
- CPU：`arm64-v8a`
- versionName：`1.0.1`
- versionCode：`10101`

Application ID、nativeファイル名、固定開発署名は旧版との更新互換性のため維持している。

## 正本

このリポジトリ `mtk-ctrl/shogi-ai` を唯一の正本とする。ソフト名は雲路へ変わったが、リポジトリ名や一部の内部ファイル名は開発史・互換性・自動化を壊さないため当面維持する。

## 主な資料

- [00_羅針盤](docs/00_羅針盤.md) — 何を目指し、どう強化を判断するか
- [04_強化ロードマップ](docs/04_強化ロードマップ.md) — 技術フェーズと到達点
- [08_開発運用と評価フロー](docs/08_開発運用と評価フロー.md) — 比較・CI・完成版化の運用
- [24_多面的評価システム構想](docs/24_多面的評価システム構想.md) — 今後の評価システムの方向
- [v1.0.1完成版記録](journal/2026-10-05_18_雲路KUMOJI_v1.0.1完成版.md)
- [CHANGELOG](journal/CHANGELOG.md)

## ビルド

ホスト版：

```bash
python3 scripts/build.py --output build/shogi-ai
```

主要な短時間検証はGitHub Actionsの `Quick Strategy CI`、Android完成版は `Build Android OEX APK` で行う。`android/VERSION` の変更を完成版APK生成の明示的な合図とする。

## 開発上の境界

外部AIを使って強さを測ることはためらわない。しかし、外部AIの考え方へ引っ張られないことを、このプロジェクトの独立性として大切にする。

最終的な夢は、既存AIや既存定跡からは生まれにくい指し回しを、自分自身の探索と経験から見つけ、それでも強い将棋AIになることである。
