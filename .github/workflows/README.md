# GitHub Actions — 現役Workflow一覧

GitHub Actions workflowは、GitHub上のrunnerでビルド・テスト・対局・成果物生成などを再現可能に実行するための仕組みである。
**既存workflowで自然に対応できる場合は再利用し、新しい研究に専用workflowが適する場合は新設してよい。**
詳細な基準は `docs/rules/R15_Workflow運用.md` を読む。

## ACTIVE — 現在利用可能な恒久基盤

| Workflow | 起動 | 用途 |
|---|---|---|
| `.github/workflows/quick-ci.yml` | 関連push / 手動 | エンジンの短時間CI。通常開発の基本検査 |
| `.github/workflows/docs-rule-check.yml` | docs/workflow変更 / PR / 手動 | Rule・ルーター・workflow一覧の整合性 |
| `.github/workflows/kifu-learning-ci.yml` | 棋譜処理変更 / PR / 手動 | 棋譜変換・ルール層validation |
| `.github/workflows/engine-match.yml` | 手動 | 汎用の内部Engine比較。既定は200ms・AdaptiveLongThink=true。研究条件は明示入力で変更 |
| `.github/workflows/engine-match-request.yml` | request更新 / 手動 | ChatGPT等から `.github/match-request.json` を検証して `engine-match.yml` をdispatchする薄い起動口。対局処理は持たない |
| `.github/workflows/position-knowledge-refresh.yml` | 知識更新request / 手動 | 承認した候補assetから採用済み局面知識snapshotをmaterialize。新候補を自動昇格しない |
| `.github/workflows/external-engine-benchmark.yml` | 関連pushでunit / 手動Benchmark | やねうら王MaterialのCore外部尺度 |
| `.github/workflows/tsume-benchmark.yml` | 手動 | 固定詰将棋データセットのBenchmark |
| `.github/workflows/android-apk.yml` | 明示的release変更 / 手動 | 完成版全車検・Android APK生成 |

## 一時比較・研究の整理

v2対v1比較、固定v2.0.0の300局自己対局・60局面研究、その追加監査、およびA/B1000局から抽出した評価急落40局面の長考研究workflowは終了済み（2026-10-08確認）。当該300局・研究記録・局面知識はR25・docs/28・29・35に従って月別データRelease `records-2026-10-01` へ分離保存し、取得後のhash一致まで確認済み。独自の長文監査報告は削除し、追加監査runも正規の研究観測を移送後に削除した。保存用の一時workflowは `docs/archive/workflows/2026-10-08/store-v2-position-research.yml` へ退避済み。

## HOLD
Book / Experience / Nightlyの旧workflowは `docs/hold/workflows/` に退避している。
H10の方針確定まではGitHub Actionsから起動できない。夜間定期対局は、現在の変革期に優先する開発があるという本人判断でも一時停止中である。H10が解決しただけで自動再開せず、R30に従う。

## ARCHIVE
終了済みの評価weight sweep、特定世代比較、特定artifact診断等は `docs/archive/workflows/2026-10-07/` に原文保存した。
再現用の履歴であり、現行Actionsとして起動しない。

## 新しい研究・比較をしたいとき
まず既存workflowで**無理なく**表現できるか確認する。
局数・ref・持ち時間・USI option・shard数の違いだけなら `engine-match.yml` が使いやすい。

一方、新しい研究手法、独自matrix、段階的screening、専用artifact、Position BankやDiagnosisなどが必要なら専用workflowを作ってよい。
一時workflowも禁止しない。ただし初回は `workflow_dispatch` を残し、重い対局jobより先に `python3 scripts/check_match_workflows.py` を通す。Build・依存導入・seed・artifact処理を汎用workflowから安易に複製しない。研究終了後にACTIVE / HOLD / ARCHIVEを整理する。

固定局数の対局を起動するときはR21に従い、先に空きrunner数を確認してrunner配分を決める。内部・外部runnerはgame_offsetを受け取り、奇数局のshardでも全体の先後交互を継続する。shards=1という入力既定を、そのまま最適なrunner配分とみなさない。

## 内部比較の着手アーカイブ
engine-match.ymlは対局後に実際の着手だけを圧縮し、played-move-archive artifactへ保存する。探索処理は変更しない。
正本は `docs/rules/R25_着手記録の保存.md`。評価欠損はmanifestに残す。artifactは期限付きであり、永続保存先への自動移送は未実装である。
