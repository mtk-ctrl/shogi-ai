# GitHub Actions — 現役Workflow一覧

GitHub Actions workflowは、GitHub上のrunnerでビルド・テスト・対局・成果物生成などを再現可能に実行するための仕組みである。
**既存workflowで自然に対応できる場合は再利用し、新しい研究に専用workflowが適する場合は新設してよい。**
詳細な基準は `docs/rules/R15_Workflow運用.md` を読む。
新規追加時はこの一覧も同じcommitで更新する。未登録は通常CIで警告（他の検査は継続）、出荷前の厳密確認は `python3 scripts/check_workflow_inventory.py --strict` を使う。

## ACTIVE — 現在利用可能な恒久基盤

| Workflow | 起動 | 用途 |
|---|---|---|
| `.github/workflows/selfplay-candidate-verification.yml` | 検証依頼ファイル変更 / 手動 | 固定した学習候補の48局面単独速度診断、完了した100/200局の合法性・終局ルール・長考・知識・実モデル使用・build出所を検証。結果と実戦手原本を月別データReleaseへhash確認付き保存。対局本体は既存汎用Workflowを使い、正式採用はしない |
| `.github/workflows/postgame-cycle-pilot.yml` | 手動 | 対局後改善循環の第1世代で固定した研究候補知識K1だけを、正式K0と分離して100局選別し、全実戦手・固定資産・監査を月別データReleaseへ保存する。正式採用や第2世代へ自動移行しない |
| `.github/workflows/selfplay-learning.yml` | 学習依頼ファイル変更 / 手動 | 完了した同一版自己対局を出所・合法性・分割漏洩検査し、小型の評価補正を学習して候補をビルド。実戦手原本とモデルは月別データReleaseへhash検証付きで保存し、エンジンへの正式採用や次の対局を自動決定しない |
| `.github/workflows/position10-adopt.yml` | 明示的な10局面採用依頼 / 手動 | 実行38091143128の研究10局面を原本から厳密検査して局面知識153→163件を採用。研究原本を月別Releaseへ保存・照合する |
| `.github/workflows/timebox80-adopt.yml` | 承認済み80局面の採用依頼 / 手動 | 2026-10-09実施の午前40・午後40局面の長考研究を検査して既存73局面へ追記。153局面をビルド検証し、既存の汎用比較Workflowで知識あり・なし100局を起動する |
| `.github/workflows/timebox40-long-research.yml` | 研究request更新 / 手動 | 指定した時間枠内で未研究の序盤・中盤・終盤計40局面を各50分研究。最大20runnerを2巡利用し原本はReleasesへ保存。既存研究との重複を除外し、新知識は自動正式採用しない |
| `.github/workflows/opening20-adopt.yml` | 明示的採用依頼のrequest更新 / 手動 | 2026-10-09承認の序盤20局面50分研究を既存53局面へ追記し、合法性・研究結果・直接選択・73件・長期保存を検証して採用版を更新する |\n| `.github/workflows/opening20-followup.yml` | request更新 / 手動 | 50分研究で終了間際に研究手が変わった序盤3局面を3runner・各30分独立再探索（固定した元Engineと知識使用、旧研究との比較、結果は自動採用しない） | 
| `.github/workflows/opening20-long-research.yml` | 選定済み局面request更新 / 手動 | 既存棋譜から抽出した未研究の序盤20局面を1台1局面・50分並列研究。研究記録だけを保存し局面知識へ自動採用しない |\n| `.github/workflows/position10-long-research.yml` | 研究依頼JSON更新 / 手動 | 採用済み局面知識と重複しない序盤3・中盤4・終盤3の計10局面を、現行エンジンで10runner各50分研究。研究原本はReleasesへ保存し、正式採用はしない |
| `.github/workflows/quick-ci.yml` | 関連push / 手動 | エンジンの短時間CI。通常開発の基本検査 |
| `.github/workflows/docs-rule-check.yml` | docs/workflow変更 / PR / 手動 | Rule・ルーター・workflow一覧の整合性 |
| `.github/workflows/nn-real-study.yml` | 学習依頼ファイル更新 / 手動 / PR検査 | 保存済み自己対局の出所・容量・棋譜合法性を検証し、研究専用ニューラルネットワークを学習。現行雲路の静的評価との勝率比較、差の大きい局面、学習済み重みを90日artifactに保存。本体の指し手は変更しない |
| `.github/workflows/nn-disagreement-study.yml` | 研究依頼更新 / 手動 / PR事前検証 | 学習済みNNと雲路の評価差を採用済み序中終判定で30局面（各10）に絞り、10runnerで各50分長考。原本と評価比較を保存し、局面知識・評価関数への自動採用はしない |
| `.github/workflows/nn-history-study.yml` | 学習依頼ファイル変更 / 手動 / PR事前検証 | 残っている標準着手記録と長期保存済み棋譜を総点検し、同一バイナリ291局と異世代雲路4,304局を区別し、明示された研究モードでは異世代の勝敗も探索的に使用。学習モデルと現行静的評価を別実行記録で比較し、成果物は期限付き保存 |
| `.github/workflows/kifu-learning-ci.yml` | 棋譜処理変更 / PR / 手動 | 棋譜変換・ルール層validation |
| `.github/workflows/bold-external.yml` | 外部検証依頼 / 手動 | 複数の評価関数候補をやねうら王Material Lv50・55で比較する専用検証。候補を自動採用しない |
| `.github/workflows/piece-value-league.yml` | 依頼ファイル変更 / 手動 | 現行Engineを固定した盤上・成駒・持ち駒の駒価値8型（現行＋大胆な7案）を独立ビルド、全28組を200ms＋条件付き長考・同一局面知識で総当たり。採用は別途判断 |
| `.github/workflows/eval-bold-league.yml` | 研究依頼ファイルの変更 / 手動 | 正式M・従来W・大胆な配点6案（P0～P5）を固定エンジンで8型総当たりし、実戦・評価の統計を記録。正式採用はしない |
| `.github/workflows/eval-wide-league.yml` | 明示的な依頼ファイル更新 / 手動 | 評価8型（現行M型、既存S/A/T型、新規X/Y/Z/W型）を総当たり。事前検査後に空きrunner数で並列実行し、全局の棋譜・評価内訳・順位を保存。候補の自動採用はしない |
| `.github/workflows/engine-match.yml` | 手動 | 汎用の内部Engine比較。既定は200ms・AdaptiveLongThink=true。研究条件は明示入力で変更 |
| `.github/workflows/variable-eval-search.yml` | オーナーの `[KUMOJI SEARCH]` Issue / 手動 | 固定した研究commitと配点一覧を使い、多数の新しい組合せを少数局で比較。共通バイナリ1本・最大10runner・標準arena/実戦手保存を再利用。候補の自動採用はしない |
| `.github/workflows/engine-match-request.yml` | オーナーのIssue作成 / request更新 / 手動 | 対局条件だけを検証し `engine-match.yml` を起動する軽量入口。通常はIssue方式でコードを変更しない。対局処理は持たない |
| `.github/workflows/position-knowledge-refresh.yml` | 知識更新request / 手動 | 承認した候補データから採用済み局面知識を生成する。新候補を自動採用しない |
| `.github/workflows/yaneuraou-nnue-trial.yml` | 専用依頼ファイル変更 / 手動 | やねうら王NNUE（公開学習済み評価）の40局対局。固定雲路200ms＋採用済み知識・長考、NNUE各1000/5000節点20局、20runner、結果と実設定・違法対局を集計。Material梯子とは別尺度で正式採用なし |
| `.github/workflows/yaneuraou-ladder.yml` | 依頼ファイル更新 / 手動 / 条件付き自動進行 | やねうら王Material版で正式棋力測定（雲路200ms・長考ON・局面知識ON）。100局ごとにレベルを1上げ、勝率30%未満で自動停止。レベル別対局記録と集計を保存し、固定エンジンcommitを引き継ぐ |
| `.github/workflows/external-engine-benchmark.yml` | 関連pushでunit / 手動Benchmark | やねうら王MaterialのCore外部尺度 |
| `.github/workflows/tsume-benchmark.yml` | 手動 | 固定詰将棋データセットのBenchmark |
| `.github/workflows/android-apk.yml` | 明示的release変更 / 手動 | 完成版全車検・Android APK生成 |

## 一時比較・研究の整理

v2対v1比較、固定v2.0.0の300局自己対局・60局面研究、その追加監査、およびA/B1000局から抽出した評価急落40局面の長考研究workflowは終了済み（2026-10-08確認）。当該300局・研究記録・局面知識はR25・docs/28・29・35に従って月別データRelease `records-2026-10-01` へ分離保存し、取得後のhash一致まで確認済み。独自の長文監査報告は削除し、追加監査runも正規の研究観測を移送後に削除した。保存用の一時workflowは `docs/archive/workflows/2026-10-08/store-v2-position-research.yml` へ退避済み。

## HOLD
旧Book / Experience関連workflowは履歴保管として `docs/hold/workflows/` に退避しており、現行運用では起動しない。夜間定期対局は、現在の変革期に優先する開発があるという本人判断で一時停止中であり、再開はR30に従う。

## ARCHIVE
終了済みの評価weight sweep、特定世代比較、特定artifact診断等は `docs/archive/workflows/2026-10-07/` に原文保存した。
再現用の履歴であり、現行Actionsとして起動しない。

## 通常の対局起動：ファイル更新不要のIssue方式
ChatGPTがGitHub Issueを1件作成し、タイトルを「`[KUMOJI MATCH] 対局名`」、本文を対局依頼JSON（従来の `.github/match-request.json` と同じ必須項目）とする。Issueの作成者はリポジトリ所有者本人に限る。`engine-match-request.yml` が依頼の入力検査を行ってから、既存の `engine-match.yml` を呼び出す。通常の対局ごとにYAMLや依頼JSONをcommitしない。

- 指定できる基本項目は `ref_a`、`ref_b`、`games`、`shards`、`go_command`、`max_plies`、`seed`、`options_a`、`options_b`。`options_a` / `options_b` はJSON**文字列**で、後者にも同じ採用済み局面知識を指定する。
- Issue方式は `go movetime N`、最大1万局・20並列・1000手、許可されたUSI設定のみ。`dry_run: true` なら入力検査だけ実施して対局は起動しない。
- Issue方式が対応していない実験は、既存の `.github/match-request.json` 更新や専用Workflowで対応する。安全性チェックに拒否された操作を別経路で不当に実行してはならない。
- この入口は起動だけを担当する。開始状況・終了結果・保存確認はR21に従って追跡する。

## 新しい研究・比較をしたいとき
まず既存workflowで**無理なく**表現できるか確認する。
局数・ref・持ち時間・USI option・shard数の違いだけなら `engine-match.yml` が使いやすい。

一方、新しい研究手法、独自matrix、段階的screening、専用artifact、Position BankやDiagnosisなどが必要なら専用workflowを作ってよい。
一時workflowも禁止しない。ただし初回は `workflow_dispatch` を残し、重い対局jobより先に `python3 scripts/check_match_workflows.py` を通す。Build・依存導入・seed・artifact処理を汎用workflowから安易に複製しない。研究終了後にACTIVE / HOLD / ARCHIVEを整理する。

固定局数の対局を起動するときはR21に従い、先に空きrunner数を確認してrunner配分を決める。内部・外部runnerはgame_offsetを受け取り、奇数局のshardでも全体の先後交互を継続する。shards=1という入力既定を、そのまま最適なrunner配分とみなさない。

## 内部比較の着手アーカイブ
engine-match.ymlは対局後に実際の着手だけを圧縮し、played-move-archive artifactへ保存する。探索処理は変更しない。
正本は `docs/rules/R25_着手記録の保存.md`。評価欠損はmanifestに残す。artifactは期限付きであり、全runの永続保存先への自動移送は未実装である。明示選択した自己対局学習・候補検証は、上記2入口で実戦手原本・モデル・結果を月別Releaseへ保存し、再取得hash一致まで確認する（R25）。


## 2026-10-15 完了研究の整理

探索効率化5分野の速度測定専用workflowは終了し、`docs/archive/workflows/2026-10-15/search-all-efficiency-research.yml` に原形を保管した。研究結果は `research/search-all-20261015/RESULTS.md`。通常対局・正式検査は既存のActive workflowを利用する。

### 自己対局後の診断原本の検証・保存

既存 `selfplay-candidate-verification.yml` の `.github/selfplay-verification-request.json` は、従来の `benchmark` / `audit` に加えて `postgame-publish` を受け付ける。これは固定research commitに保存した初回の選別研究packageを検証し、月別データReleaseへ保存・再取得hash/API digestを照合するモード。全実戦手の再取得、学習、対局、正式採用は起動しない。固定した候補ref/比較ref、match_run=0、既存5項目の受付を保つ。

保存前に入力器・解析器・保存検証の検査を実行する。packageは許可された7ファイル・上限16MiBに限定し、選択96例以内/各局4以内・完全合法履歴・50/500ms条件・実バイナリhashを照合する。全PV/未着手候補表/探索木を含めず、payload内のバイナリは実行しない。初回のGit受渡しsnapshotが履歴に残る容量もpublicationへ明示する。継続的な全対局のGit保存へ広げない。
