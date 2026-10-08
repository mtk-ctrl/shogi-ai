---
rule_id: R15
status: active
authority: normative
---

# GitHub Actions Workflow運用

## Workflowとは
GitHub Actions workflowは、GitHub上のrunnerに「いつ・何を・どの条件で実行するか」を記述する自動実行レシピである。
コードやMarkdownを保存するために必須なのではなく、GitHub上で再現可能な実行・検証・並列処理・定期処理・成果物生成が有用なときに使う。

## 基本姿勢
workflowの数を減らすこと自体を目的にしない。
**既存workflowで無理なく表現できるなら再利用し、新しい研究・実験に専用workflowの方が明確、安全、再現しやすいなら新設してよい。**

既存workflowへ無理に押し込んで、条件が分かりにくくなる、runner配分が不自然になる、artifactや研究フェーズを失う、といったことは避ける。

## Workflowを使う価値が高い場面
- 関連コードが変わるたびに自動検証したいCI
- APK・releaseなど、GitHub上の一定環境で成果物を再現生成したい処理
- 多数runnerを使う比較対局・探索実験・パラメータ探索
- 同じ条件を将来もう一度再現したい研究
- 複数段階の研究フェーズ、集約、artifact保存が必要な実験
- 外部Benchmarkや詰将棋Benchmarkなど、固定尺度として継続利用する処理
- 明示的に採用された定期実行

## 既存workflowをまず検討する場面
次のような違いだけなら、既存workflowの入力変更で自然に表現できるかを最初に確認する。

- 局数の違い
- 持ち時間・go commandの違い
- candidate / baseline refの違い
- USI optionのON/OFFやweightの違い
- shard数の違い

自然に表現できるなら、内部Engine比較では `.github/workflows/engine-match.yml` を再利用してよい。

## 新しいworkflowを作ってよい場面
次のいずれかに該当するなら、1回限りの研究でも専用workflowを作ってよい。

- 新しい研究手法で、既存workflowでは実験構造を正しく表現できない
- 独自のmatrix、段階的screening、決勝、再解析などが必要
- Position Bank、Diagnosis、外部エンジン、特殊dataset等の専用処理が必要
- runner構成・artifact・集約方法が既存workflowと大きく異なる
- 再現性や検証可能性のため、実験条件をYAMLとして固定する価値が高い
- 汎用workflowへ機能を詰め込みすぎるより、専用workflowの方が理解しやすい

研究ブランチ上だけで実行してもよいし、GitHub Actions上でmainを基準に動かす必要があるなら一時的にmainへ置いてもよい。

## Workflowを使わなくてよい場面
- 単純なMarkdown更新
- 小さなファイル整理
- GitHub runnerや並列処理を必要としない軽量な集計
- ChatGPT側で安全に完結し、GitHub上での再現実行に価値がない処理

「一回限りだからworkflow禁止」ではない。GitHub上で実行する価値があるかで判断する。

## 現役・保留・履歴
- **ACTIVE**: `.github/workflows/` に置く。現在利用可能なworkflow。
- **HOLD**: `docs/hold/workflows/` に置く。方針未決で、今は実行させないもの。
- **ARCHIVE**: `docs/archive/workflows/` に置く。終了済み研究・過去実験の再現資料。

一時研究workflowは、研究終了後に
1. 今後も使う → ACTIVEのまま整理
2. 方針未決 → HOLD
3. 役割終了 → ARCHIVE
のいずれかへ整理する。

保存日時やrun履歴の新しさだけでは状態を決めない。

## trigger
- `push` / `pull_request`: 変更のたびに本当に必要なCIに使う。
- `workflow_dispatch`: Benchmark・比較・研究・releaseなど、必要時に明示起動する処理に使う。
- `schedule`: 採用済みの定期運用だけに使う。未決の研究方針へ勝手にscheduleを付けない。
- workflowファイル自身へのpushを実験開始のためだけに常用しない。必要性がある一時研究では使用してもよいが、終了後に整理する。

## 比較対局
内部Engine比較は、まず `.github/workflows/engine-match.yml` で自然に表現できるか確認する。
表現できるなら再利用する。新しい研究設計に専用workflowが適するなら無理に統合しない。

局数、candidate / baseline ref、持ち時間、USI option、shard数だけの違いは、原則として専用workflowを新設せず `engine-match.yml` の入力で表現する。
対局を依頼された時点で既存workflowの適否を判断し、既存基盤で足りるのにBuild・依存導入・seed・artifact処理を専用YAMLへ複製しない。

専用workflowが必要なのは、独自matrix、段階的screening、Position Bank、Diagnosis、特殊dataset、長時間の局面研究等、実験構造そのものが既存workflowでは表現できない場合とする。
専用の対局・局面研究workflowを作る場合は、初回は `workflow_dispatch` を入口として残し、重いjobを開始する前に `python3 scripts/check_match_workflows.py` を通す。workflowファイル自身へのpushだけを初回実験開始の合図にしない。少なくとも次を機械検査する。
- GitHub Actions式を `\\${{ ... }}` のように誤ってescapeしていないこと
- seedの数値がUSI整数範囲を明白に超えていないこと
- `arena.py` / `position_arena.py` を実行するworkflowに `python-shogi==1.1.1` の導入があること
- リポジトリに存在しないBuild入口（例: ルート `CMakeLists.txt` がない状態での `cmake -S .`）を使っていないこと
- 標準 `engine-match.yml` がリポジトリ既定の `scripts/build.py` とseed事前検査を維持していること

対局runnerの配分はR21に従う。起動前に空きrunner数を確認し、汎用workflowでは `shards` を実際に使えるrunner数へ設定する。

## 外部Benchmark
やねうら王Material尺度は `.github/workflows/external-engine-benchmark.yml` を標準入口とする。
新しい外部研究がこの尺度と異なるなら、目的を明記した専用workflowを作ってよい。
外部AIの利用境界はR50に従う。

## 新しいworkflowを作るとき
1. 既存workflowで自然に表現できるか確認する。
2. 無理な共通化にならないか確認する。
3. 実験目的・入力・出力・artifactを明確にする。
4. triggerを必要最小限にする。
5. 対局ならR20/R21に従う。
6. mainへ置く場合は `.github/workflows/README.md` に用途を登録する。
7. `python3 scripts/check_workflow_inventory.py` と `python3 scripts/check_match_workflows.py` を通す。
8. 対局・局面研究workflowなら、preflight検査を通過してから重い対局jobを開始する。
9. 研究終了後にACTIVE / HOLD / ARCHIVEを見直す。

## 整合性チェックの扱い（2026-10-09）
- workflowの新設・改名・退役時は、実行用YAMLと `.github/workflows/README.md` のACTIVE一覧を**同一変更・同一commit**で同期する。AIが一覧修正と検査まで実施し、人へ手作業を戻さない。
- pushでの文書チェックはmainを対象とし、研究branchはPR時または明示起動で検査する。同じ変更に対するpushとPRの二重通知を避ける。
- `python3 scripts/check_workflow_inventory.py` は未登録を警告として出し、他の検査まで継続する。`--strict` は一覧を完全に整理するときの手動確認用であり、未登録もエラーにする。
- 存在しない参照先、必須の動作設定違反などの実害はエラーとし、日本語の言い換え・説明文の未登録は警告として扱う。警告も放置せず、作業区切りで同じ修正に含める。
- エラーになった場合は先に該当検査・修正箇所・同一原因の既存runを確認する。理由なく同じ失敗を繰り返さず、通知設定だけで原因を隠さない。
