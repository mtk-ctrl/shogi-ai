# GitHub Actions — 現役Workflow一覧

GitHub Actions workflowは、GitHub上のrunnerでビルド・テスト・対局・成果物生成などを再現可能に実行するための仕組みである。
**作業ごとにworkflowを作る必要はない。** 詳細な基準は `docs/rules/R15_Workflow運用.md` を読む。

## ACTIVE — mainに残す恒久基盤

| Workflow | 起動 | 用途 |
|---|---|---|
| `.github/workflows/quick-ci.yml` | 関連push / 手動 | エンジンの短時間CI。通常開発の基本検査 |
| `.github/workflows/docs-rule-check.yml` | docs/workflow変更 / PR / 手動 | Rule・ルーター・workflow一覧の整合性 |
| `.github/workflows/kifu-learning-ci.yml` | 棋譜処理変更 / PR / 手動 | 棋譜変換・ルール層validation |
| `.github/workflows/engine-match.yml` | 手動 | 汎用の内部Engine比較。個別比較workflowの代替 |
| `.github/workflows/external-engine-benchmark.yml` | 関連pushでunit / 手動Benchmark | やねうら王MaterialのCore外部尺度 |
| `.github/workflows/tsume-benchmark.yml` | 手動 | 固定詰将棋データセットのBenchmark |
| `.github/workflows/android-apk.yml` | 明示的release変更 / 手動 | 完成版全車検・Android APK生成 |

## HOLD
Book / Experience / Nightlyの旧workflowは `docs/hold/workflows/` に退避している。
H10の方針確定まではGitHub Actionsから起動できない。

## ARCHIVE
一回限りの評価weight sweep、特定世代比較、特定artifact診断等は `docs/archive/workflows/2026-10-07/` に原文保存した。
再現用の履歴であり、現行Actionsとして起動しない。

## 新しい比較をしたいとき
原則 `engine-match.yml` の入力を変える。
新しいYAMLを作るのは、既存workflowでは表現できず、かつ今後も繰り返し使う能力だけである。

固定局数の対局を起動するときはR21に従い、先に空きrunner数を確認して `shards` に設定する。
