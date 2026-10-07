---
rule_id: R15
status: active
authority: normative
---

# GitHub Actions Workflow運用

## Workflowとは
GitHub Actions workflowは、GitHub上のrunnerに「いつ・何を・どの条件で実行するか」を記述する自動実行レシピである。
コードやMarkdownを保存するために必須なのではなく、GitHub上で再現可能な実行・検証・並列処理・定期処理・成果物生成が必要なときに使う。

## 恒久workflowを使うべき場面
次のいずれかに該当する処理は、原則として既存workflowを使う。

- 関連コードが変わるたびに自動検証すべきCI
- APK・releaseなど、GitHub上の一定環境で再現して成果物を作る処理
- 多数のrunnerを使う比較対局・外部Benchmark
- 同じ形式で繰り返す詰将棋Benchmark等
- 明示的に採用された定期実行
- チャットや担当AIが変わっても同じ条件で再実行できる必要がある処理

## 新しい恒久workflowを作らない場面
次の用途だけのためにmainへworkflowを増やさない。

- 1回限りの評価weight候補
- 特定commit・特定run ID専用の検証
- 「100局だけ」「この候補だけ」等の個別実験
- 既存の汎用比較workflowで入力値を変えれば実行できる比較
- 小さな集計・解析・文書更新
- 結果が出た後に二度と同じ入口から起動しない実験

個別実験で特殊workflowが必要なら研究ブランチ上に一時的に作成してよいが、恒久用途がない限りmainへ残さない。

## 現役・保留・履歴
- **ACTIVE**: `.github/workflows/` に置く。GitHub Actionsから実行できる恒久基盤だけ。
- **HOLD**: `docs/hold/workflows/` に置く。方針未決で、実行させてはいけないもの。
- **ARCHIVE**: `docs/archive/workflows/` に置く。過去の実験再現用で、現行運用には使わない。

保存日時やrun履歴の新しさではなく、この配置を状態の基準とする。

## trigger
- `push` / `pull_request`: 変更のたびに本当に必要なCIだけ。
- `workflow_dispatch`: Benchmark・比較・releaseなど、人またはChatGPTが必要時に明示起動する処理。
- `schedule`: 採用済みの定期運用だけ。未決の研究方針にscheduleを置かない。
- workflowファイル自身へのpushを「実験開始ボタン」の代わりに使わない。

## 比較対局
内部Engine比較は原則 `.github/workflows/engine-match.yml` を使う。
候補ref、基準ref、局数、go command、USI options、shard数を入力し、同じ種類の比較のたびに新しいYAMLを作らない。

対局runnerの配分はR21に従う。起動前に空きrunner数を確認し、`shards` を実際に使えるrunner数へ設定する。

## 外部Benchmark
やねうら王Material尺度は `.github/workflows/external-engine-benchmark.yml` を使う。
外部AIの利用境界はR50に従う。

## 新しいworkflowをmainへ追加するとき
1. 既存workflowの入力追加で代替できないか確認する。
2. 同じ処理を今後も再利用するか確認する。
3. triggerを必要最小限にする。
4. 対局ならR20/R21に従う。
5. `.github/workflows/README.md` のACTIVE一覧へ登録する。
6. `python3 scripts/check_workflow_inventory.py` を通す。
7. 一時実験ならmainへ残さず、終了後にarchiveまたは削除する。
