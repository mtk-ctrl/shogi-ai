---
rule_id: R70
status: active
authority: normative
---

# 記録・Journal・バージョン

## 文書の役割
- `docs/rules/`: 現在どうするか。唯一の運用規範。
- `docs/00_開発ルーター.md`: 作業別の読み先だけ。Rule本文を書かない。
- `README.md`: 現在地と利用者向け概要。Ruleの正本にしない。
- `docs/decisions/`: なぜ採用したか。
- `journal/`: その時点で何が起きたか。
- `docs/archive/`: 旧文書。現在の指示には使わない。
- `docs/hold/`: 結論を出してはいけない保留領域。

## Engine世代とreleaseの意味
- 正式採用したEngine世代には `KUMOJI vX.Y.Z` の世代番号を付けてよい。現在の正式Engine世代は **KUMOJI v2.0.0** である。
- 正式採用されたEngine実装は `main` へ統合し、`main` を現行本体の正本とする。正式採用後の実装を研究branchだけに残さない。
- 同じEngine世代内でも実装変更はあり得るため、正確なコード状態は `main` のcommit SHAで特定する。
- Android / OEXの `vX.Y.Z` はR60に従って完成版化したrelease番号であり、Engine世代とは別に管理する。現在の最新完成版はv1.0.1である。
- Android/OEX releaseがv1.0.1のままでも、main Engineがv2.0.0であることと矛盾しない。
- 棋力比較の基準commitは `benchmarks/baseline_ref.txt` で管理し、Engine世代番号や製品release番号と混同しない。
- READMEでは「現在のEngine世代」「mainの実装状態」「最新Android/OEX release」を分けて記述する。

## journal
重要な実装、比較、採用・不採用、方針変更は `journal/YYYY-MM-DD_NN_テーマ.md` に残す。
同日のNNはmainへ統合された順で確定し、一度確定した番号を後から振り直さない。
`journal/CHANGELOG.md` は索引として扱う。

## 履歴と現行を混ぜない
過去journalやdecisionに現行と異なる数値・条件が書かれていても、それを現行Ruleへ自動復活させない。
過去文書へ「現在は違う」という理由だけで内容改変を加えない。必要ならリンク修正または注記に留める。

## 文書整理
規範文書をRulesへ移した後、旧文書に履歴価値があればarchiveへ原文保存する。
元URLが多数参照されている場合は、旧場所に短い移転案内だけを残してよい。
