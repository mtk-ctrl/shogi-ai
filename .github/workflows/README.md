# GitHub Actions — 現役Workflow一覧

GitHub Actions workflowは、GitHub上のrunnerでビルド・テスト・対局・成果物生成などを再現可能に実行するための仕組みである。
**既存workflowで自然に対応できる場合は再利用し、新しい研究に専用workflowが適する場合は新設してよい。**
詳細な基準は `docs/rules/R15_Workflow運用.md` を読む。
新規追加時はこの一覧も同じcommitで更新する。未登録は通常CIで警告（他の検査は継続）、出荷前の厳密確認は `python3 scripts/check_workflow_inventory.py --strict` を使う。

## ACTIVE — 現在利用可能な恒久基盤

| Workflow | 起動 | 用途 |
|---|---|---|
| `.github/workflows/selfplay-candidate-verification.yml` | 検証依頼ファイル変更 / 手動 | 固定した学習候補の48局面単独速度診断、完了した100/200局の合法性・終局ルール・長考・知識・実モデル使用・build出所を検証。結果と実戦手原本を月別データReleaseへhash確認付き保存。対局本体は既存汎用Workflowを使い、正式採用はしない |
| `.github/workflows/postgame-spiral.yml` | 明示request / 手動 / 関連PR軽量検査 | 凍結予算内の評価学習/研究知識循環、追加研究、予算付き分岐練習、段階/先後/自作相手の固定練習、保存/検査。PRでは保存観測の再現と実Engine配線試験。正式採用しない |
| `.github/workflows/postgame-cycle-pilot.yml` | 手動 | 旧G1の固定K0/K1比較を保持。追加の研究モードは保存済み循環checkpointから原本の実バイナリ/別知識を復元し、既存arenaで比較する。監査/長期保存と研究親選択は循環制御が担当。正式採用しない |
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

自己対局後改善の選別100局と、選別の監査・保存が通った場合の一度だけの200局確認は、`.github/postgame-pilot-request.json` の明示更新から同じ `postgame-cycle-pilot.yml` 内の最小権限launcherを経て既存の手動入口を起動できる。固定候補・親SHA・100/200局・操作ID・1〜20分割以外は拒否し、同じ操作IDの本体runがあれば再起動しない。workflow自身のpushや定期起動では対局を始めない。

自己対局後改善の完了runは、既存selfplay検証入口の `postgame-audit` モードへ、凍結candidate_ref・baseline_ref・実match_runを明示して監査する。全実戦手・終局・設定・先後・実バイナリ・知識hashと保存再取得を照合する。保存バイナリでの知識loader再現は元対局の起動時ログと区別する。監査の修正だけで原対局を再実行しない。

200局の起動前には先行する100局監査runの成功・固定候補・得点率50%以上・合法性/終局検証・Release保存receiptを再取得して照合する。手動入口のplanでも依頼JSON・重複操作・同じ前提を検査する。終局判定や候補は変えず、監査のログ取得では制御文字を表示せず除去し、外部ホストへのredirectに認証を転送しない。

第1世代試運転は選別100局・確認200局・全手監査/Release保存を完了し、強化未証明で終了した。完了済み操作IDの再起動は拒否/抑止する。基盤は次の明示研究で再利用するACTIVEとして保持するが、今回の依頼を更新して対局を追加しない。新世代には別の事前PLANと固定入力の設定が必要で、正式Engine/採用知識を自動更新しない。

### 改善循環の中核の検査

`postgame-cycle-pilot.yml`のPR用code-ciは、既存検査に加えて `test_postgame_ranker / test_postgame_spiral / test_postgame_cycle` を実行する。選別・学習提案・世代制御の研究基盤を検査するもので、PRから対局は開始しない。新しい制御ライブラリを既存G1の固定ref起動器へ自動接続したものではない。範囲と残る実行アダプターは[説明](../../research/postgame-spiral-core-20261017/README.md)を参照する。

### 自己対局原本から再分析への実働接続

既存 `selfplay-candidate-verification.yml` の `postgame-bridge` モードは、明示した完了済み `engine-match.yml` の原本と実バイナリを取り込み、固定親の評価設定で再分析→学習準備→保存receipt→世代台帳への引渡しを行う。通常入口と原対局は再利用し、新しい対局workflowは作らない。入力は既存verification依頼ファイルと、不変candidate_ref内の `bridge-request.json`。完了run・所有者の起動意図・build/バイナリ・知識・全手・終局・設定を照合する。

新規知識の汎用配布や候補の選別/確認を自動dispatchする入口ではない。初回は正式版同士2局のsource試験であり、正式採用・多世代の棋力向上と区別する。

### 予算付きの多世代改善循環

`postgame-spiral.yml`は、`research/postgame-cycles/<cycle_id>/PLAN.json`を不変commitで指定して一度だけ起動する。通常対局本体`engine-match.yml`のBuild/arena/分割/保存を再利用し、既存の手動入力へ9軸の評価設定を渡す。Issue受付の許可項目は変更しない。`.github/postgame-spiral-request.json`は`enabled:false`なら何も起動しない。有効な明示依頼は`cycle_id/plan_ref/repair`と任意の`inspect_only`だけ。Workflowファイルの保存そのものでは対局を始めない。

制御は1つの手動runの中で動く。対局中はGitHub CLIの`run watch`で、保存済みIDの本体完了を待つ。毎時scheduleやworkflow_runの連鎖は使わない。各起動時に他runの稼働/待機jobを取得し、制御job自身が占める1枠も除いて、残る空きへ局数を均等配分する。他のrunを停止しない。容量待ちも既知のrun完了を待ってから再取得する。

月別データReleaseへ操作意図→dispatch応答ID→全手監査/原本→再分析/学習→実Engine検査→結果の順に追記し、各保存を再取得hash/API digestで照合する。異なる内容の上書きはしない。HTTP応答が不明なら二重起動せず停止する。障害修正後の`repair:true`は保存済み本体を調べ直すための入口であり、対局の再起動命令ではない。応答ID自体が欠けた操作は明示照合が必要で、自動再送しない。

通常比較まで接続している経路は**評価9軸の学習**と、事前固定した**知識だけの研究循環**。知識候補は既存研究pilotへ不変checkpointを渡し、正式163件を上書きせず別snapshotで比較する。知識だけのPLANでは評価学習・未使用群の候補評価を実行しない。旧PLANは材料不足でも固定親・分割台帳・適格例を保持して次の原本へ進む仕様であった。新しい手動開始では`progress_policy`の固定を必須とし、材料数/独立群数の不足が所定回数続けて減らないと`research_review_required`で追加対局を止め、実際の履歴付き研究課題を残す。知識検証待ちも評価学習とは独立に残し、通常比較へ未接続なら無視して対局を追加しない。[段階実装](../../research/self-improvement-20261017/ROADMAP.md)を参照する。

実Engine検査に不合格の候補は比較せず親保持。100局50%以上の場合だけ固定候補で一度200局を行い、原本との完全棋譜重複除外後も概算95%下限50%超などの条件を満たしたときだけ研究親を更新する。世代数/総局数を増やさず停止し、正式Engine/版/既定値/採用知識/baselineは変更しない。PRのcode-ciは全postgame検査に加え、固定hashの保存済み2診断を取得して元の準備結果を完全再現し、新しい進捗判断をartifactへ残す。追加解析を再実行しない。実Engineの配線検査は別の合成試験として実行する。

多世代制御のrequest launcherも、読み込む研究モジュールに必要な`python-shogi==1.1.1`を導入してから手動入口へ接続する。launcherの成功と本体/対局の開始は別々に確認する。

新しい手動開始は`knowledge_policy`の固定も必須とする。実装値は`postgame_knowledge.POLICY_KNOWLEDGE`。prepareの学習群にある確認済み研究手を別知識へ変換し、親の200msを2回再確認、実バイナリで無効時一致/取り合い/速度/対象での研究IDと着手変更を検査する。通過時だけA=親+候補/B=親の固定fileと配布情報を同じ研究packageへ保存する。元知識との競合や、親が別の未比較手を選ぶ場合は採用しない。元の採用知識の上書き・Issue入力の拡張はしない。

第2段階Aは**研究知識の準備と配布入力生成**までだった。後続の第2段階Bは、保存済みcheckpointを使う知識比較と研究親の知識引継ぎへ接続する。現在の評価候補比較の条件は維持する。PRの配線試験は明示的な仮の研究比較を使うためresearchへの流用を拒否し、短いarena試験の手を学習教師や棋力結果にしない。[第2段階Aの固定範囲](../../research/self-improvement-20261017/KNOWLEDGE_PLAN.md)。

完了後の`inspect_only:true`は、contents/actions読取り権限だけで全stageのReleaseを再取得し、実戦手/終局/原本hash・保存バイナリ/知識・分割/未使用履歴・操作receiptを照合し、世代制御を最初から再現して最終台帳一致を確認する。対局・再分析・学習・保存上書きは行わない。元Rawからの先読み一致/不一致・時間/探索統計も小さく復元し、欠損は欠損として残す。


### 第2段階B：追加研究・知識だけの循環・観測の保存

新PLANは`followup_policy`へ理由別の追加研究の上限を、知識循環なら`knowledge_execution_policy`へ100/200局・実利用必須・正式採用なしを固定する。学習群だけを親ごとに一度調べ、元診断と追加観測を分け、調査済み状態を保存する。知識の候補が実戦で0回利用なら200局へ進まない。確認成功時だけ研究親の知識を引継ぎ、次の原本は両者ともその知識を使う。旧親の特徴は混ぜない。

`postgame-cycle-pilot.yml`の`spiral_checkpoint`は、保存済み操作意図・hash/API digest確認済み原本・事前検査済み別知識だけを読み、元の実バイナリを復元する。通常Issueの入力や汎用engine-matchを変更せず、旧G1の完了操作を再起動しない。新研究モードは元の実build出所を引継ぐもので、新たなbuildとは呼ばない。全手/終局/設定/知識/実バイナリ/利用/重複を再検査して循環側で長期保存する。

`postgame-spiral.yml`の`publication_only:true`は固定8件の追加解析結果を読み取り専用で照合し、月別Releaseへ保存する入口。依頼ファイルには`cycle_id=saved-followup-20261018-01`、不変`plan_ref`、`repair:false`、`publication_only:true`を明示する。対局・再分析・学習・世代更新を起動しない。PRでは同じ保存観測を再計算して検査するが、追加解析を繰り返さない。

今回の実データは8課題/32探索/詰み1確認、新規知識0。100/200局と知識更新後の実世代は未実行。分岐試験と短い実Engine配線の範囲は[結果](../../research/self-improvement-20261017/FOLLOWUP_RESULTS.md)を参照する。


2026-10-18 第3段階A：`postgame-spiral.yml` の明示的 `practice_only` は保存済み学習局面から一度だけ分岐練習する独立モード。固定計画/コードref/原本hash・実バイナリ/知識を照合し、最大4局面×2分岐×2状況・各最大16新規手を記録、群漏洩を隔離して既存診断/候補準備へ渡す。未決着に引分報酬を付けず、強制初手の探索値を作らない。通常の100/200局比較・多世代対局は起動しない。原本/再分析/候補準備を月別Releaseへ保存し再取得hashを確認する。自動世代制御への練習挿入は後続であり、通常の `control` へこのモードを黙って挿入しない。手動本体の重複/attempt再試行を拒否する。参照：[固定条件](../../research/self-improvement-20261017/PRACTICE_PLAN.md)。

第3段階Cでは、新しいPLANに`practice_cycle_policy`を固定した通常`control`だけで、材料不足時に1局面×2分岐×2状況の練習を挿入できる。通常対局と別に最大2回/8練習局、探索指示時間の予約を管理し、親別の完了IDと検証群の使用履歴を引き継ぐ。再分析・既存の知識生成・読み足し知識経路へ渡し、候補ができた場合だけ既存の検査と通常比較へ進む。実行前の台帳保存後に応答を失った場合は再生成せず保存結果を照合する。失敗時の練習原本も期限付きartifactへ保持する。旧PLAN・独立`practice_only`・正式Engineを変更しない。参照：[固定試験計画](../../research/postgame-cycles/practice-cycle-smoke-20261018-01/PLAN.md)。

研究ブランチ `research/value-learning-20261018` の `postgame-spiral.yml` は自己対局の勝敗による9配点学習を、3候補各100局→独立1000局→研究親継承と300局の新規自己対局・次のモデル学習まで検証する。実対局は既存 `engine-match.yml`、記録監査・Release保存は既存helpersを再利用する。正式なEngineや既定値は変えない。

研究ブランチ `research/structured-eval-20261019` の同じ入口には `structured_only` を追加。駒配置・双方玉距離・持駒・攻守・可動性を序中終で学ぶ4,893係数の学習評価を、固定3尺度の100局選別→別1000局確認→通過時300局と評価表を継承した次モデルの学習へ接続する。最大1600新規局。`.github/structured-value-request.json` は無効時に起動せず、有効時は固定candidate_refとrequest_idを要求する。正式Engineや知識の自動採用をしない。
