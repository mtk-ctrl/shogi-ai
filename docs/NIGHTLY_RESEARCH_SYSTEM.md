# Nightly Research System

## 位置付け
この文書はNightlyの構造設計を説明する。
現行運用Ruleは `docs/rules/R30_夜間研究.md`、対局条件はR20、runner運用はR21を正本とする。
整理前の全文は `docs/archive/pre-router/NIGHTLY_RESEARCH_SYSTEM.md` に保存した。

Book / Experienceの将来方針は `docs/hold/H10_Book・Experience方針保留.md` で保留中であり、この文書では決めない。

## 現在の状態
2026-10-07の本人確認により、変革期の優先課題へ開発を集中するため、夜間の定期対局は一時停止している。
将来は夜間対局を行いたい意向があるが、再開時期は未決定である。停止範囲と再開判断はR30に従い、Book / Experience方針の決定だけでは再開しない。
以下は将来の構造設計であり、現在稼働している処理の説明ではない。

## 目的
夜間に大量の経験・比較・診断材料を作り、翌日の日中研究へつなぐ。
Nightlyが新しい評価概念を勝手に簡易実装して置き換えることはしない。

## フェーズ
### Phase 0 — Freeze / Build / Sanity
一晩のChampion、commit、設定、利用可能capabilityを固定する。

### Phase 1 — Experience generation
自己対局・既存資産を使い、局面・棋譜・探索telemetryを増やす。
Book / Experienceの具体的な更新方式はH10の決定後に定義する。

### Phase 2 — Challenger screening
事前登録された仮説・候補だけを比較する。
原因の異なる変更を混ぜない。

### Phase 3 — Focused validation
有望候補を先後交換・別seed等で再確認する。

### Phase 4 — Diagnosis / Deep re-analysis
評価急変、敗着候補、探索不足等を深掘りし、Position Bank / Problem Suite / Daytime Research Backlogへ送る。

## データ
標準対局ではRaw Match Recordを残す。
詳細は `docs/26_対局データ収集・分析・学習設計.md` を参照する。

## Capability gates
未実装機能を実装済みとして扱わない。
代用品で結果を作って「新Nightly完成」と呼ばず、欠落はcapability gapとして明示する。

## 朝の出力
勝敗だけでなく、実行条件、局数、違法手、候補比較、評価急変、問題局面、capability gapをまとめる。
Engine / strategyのmain昇格は夜間処理だけで自動決定しない。
