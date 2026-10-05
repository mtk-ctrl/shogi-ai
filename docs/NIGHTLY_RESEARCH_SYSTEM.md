# Nightly Research System

## 目的

夜間処理は Book 専用学習ではない。`shogi-ai` 全体を強くするための **Experience / Diagnosis / Engine experiment / Benchmark** 基盤とする。

夜間に自動で行うのは「大量の経験を作る」「弱点・未知・有望な差分を抽出する」「登録済みの仮説を比較検証する」「翌日の研究材料を作る」までである。新しい評価概念そのもの（Influence、Coordination 等）の設計・実装は日中の Engine 設計ループで行い、登録された実験を次の夜に検証する。

外部AIは教師にしない。やねうら王等は固定条件の物差しとして使い、その指し手を自動教師として模倣しない。

## 不変原則

1. **Champion固定**: 一晩の開始時点の `main` を Champion とし、その晩は変更しない。
2. **原因を混ぜない**: Engine変更、Experience変更、Book変更は別比較にする。
3. **先後を必ず対にする**: 同一開始条件で先後を入れ替えた paired games を基本単位にする。
4. **Bookの責任境界**: Bookは離脱時局面を主評価し、終局勝敗は補助統計とする。終局結果だけでBook手を罰しない。
5. **勝敗だけを見ない**: 評価内訳、探索量、速度、評価急変、局面種別を残す。
6. **自動昇格しない**: 夜間結果だけで `main` を変更しない。朝に人間＋ChatGPTが結果を確認して採否を決める。
7. **Noveltyを悪手と混同しない**: 珍しさだけを報酬にしない。独自手は深い再探索・その後の成績とセットで評価する。
8. **経験を資産化**: 対局を使い捨てず、問題局面・失敗局面・新奇成功局面を Position Bank に蓄積する。

## 一晩のフェーズ

標準実行時間は JST 00:05–05:20。05:20以降は新規対局を開始せず、集計を優先する。ジョブのハードタイムアウトは 330 分。

### Phase 0 — Freeze / Build / Sanity

- 開始SHA、Book blob、Experience signature、評価パラメータを記録。
- Championを一度だけビルド。
- unit tests / opening-book USI smoke / arena 2局 smoke を実行。
- 失敗した場合は本戦を行わず診断Artifactを残す。

### Phase 1 — Experience generation（目安40%）

4レーンを役割分担する。

- Lane E0: Champion vs Champion、Book ON。通常の実戦分布。
- Lane E1: Champion vs Champion、Book OFF。Bookに隠れない序盤・探索の経験。
- Lane E2: Position Bankから層化抽出した開始局面。過去の弱点を再訪。
- Lane E3: controlled diversity。評価差の小さい上位候補だけに限定した探索的分岐。完全ランダム手は禁止。

E2/E3は runner が対応するまでは「未実装」と明示し、E0/E1だけで代用したことにしない。機能が未実装ならレポートに capability gap として残す。

### Phase 2 — Challenger screening（目安20%）

Challengerは2系統。

#### 自動生成してよい候補

設定だけで再現できるものに限定する。

- 評価4大weightの局所変異（Safety / Pressure / Activity / Danger）
- 設定で切替可能な探索機能（Quiescence、MateAssist、ExperienceCache等）
- Book ON/OFF はBook効果の比較であり、Engine強化候補とは別タグにする。

自動候補は一度に1～2要素だけ変更する。過去の結果がある場合は有望方向を優先するが、10–20%は探索枠として反対方向・遠方候補を残す。

#### 日中に登録する候補

コード変更が必要な仮説は自動生成しない。例:

- Influence（効き・支配）
- Coordination（連携・形）
- Space
- Mobility/Freedom拡張
- Flexibility/Irreversibility
- 局面別weight
- 探索延長・新しいordering

実験ブランチ/commitと「何を変えたか」「狙う能力」「Ablation方法」を manifest に登録し、夜間はその manifest を読んで比較する。

#### 予選方式

- 同一開始条件で先後反転した20ペア（標準40局）。
- illegal > 0 は失格。
- 明確な劣勢候補はここで停止。
- 上位3候補程度を本戦へ送る。
- 小差候補は捨てず、uncertain として再試験候補に残す。

### Phase 3 — Focused validation（目安25%）

予選上位候補を200–500局相当まで追加検証する。計算時間に応じて逐次配分し、有望候補へ多く割り当てる。

評価は少なくとも以下を分離する。

- overall score / Elo estimate
- startpos / Position Bank
- opening / middlegame / endgame
- king-danger / mobility / material-imbalance / control-conflict / surprise
- nodes / depth / wall time / TT / experience cache
- Book使用時はBook離脱時評価と終局結果を分離

### Phase 4 — Diagnosis / Deep re-analysis（目安15%）

その晩の情報量が高い局面を再解析する。

優先順位:

1. 評価急落: 短区間で評価が大きく悪化した局面
2. Surprise: 大幅有利評価から敗北、または大幅不利評価から勝利
3. Disagreement: Champion/Challenger、短時間/長時間で最善手が異なる局面
4. Blind spot: 既存評価内訳が総じて良いのに深い探索では悪い局面
5. Valuable novelty: 既存版/Bookと違う手だが深い再探索でも悪化せず、反復成績も良い局面

通常50msに対して深掘りは500msを初期値とする。対象数を絞り、時間切れ時は重要度順に処理する。

## Position Bank

### 保存単位

各レコードに最低限以下を持つ。

- stable id
- source run / game / ply
- SFEN または startpos + moves
- side to move
- phase
- tags[]
- Champion evaluation total
- evaluation breakdown（Material/Safety/Pressure/Activity/Danger、将来軸を追加）
- shallow bestmove / score
- deep bestmove / score
- final game result
- surprise magnitude
- novelty metadata
- first_seen / last_used / use_count

### 自動タグ

初期タグ:

- `opening`, `middlegame`, `endgame`
- `king-danger`
- `low-mobility`
- `material-imbalance`
- `control-conflict`
- `eval-swing`
- `surprise`
- `disagreement`
- `blind-spot`
- `valuable-novelty`
- `unclassified`

タグ定義は数値閾値とともに version 管理する。閾値変更で過去局面の意味が不明になることを避ける。

### 翌晩の抽出

Position Bankからの開始局面は完全ランダムにしない。初期配分:

- king-danger 20%
- influence/control 15%
- mobility 15%
- material-imbalance 10%
- endgame 10%
- surprise 10%
- disagreement/blind-spot 10%
- diversity random 10%

同一レコードの使い過ぎを防ぐため `last_used` と `use_count` で減衰させる。タグ重複は最も不足している層へ割り当てる。

## Experienceの保存方針

全局面を永久保存しない。

- raw game artifact: 14日
- compact nightly report: 180日
- Position Bank: 長期保持。情報量の高い局面だけ
- regression/problem suite: 原則永続。解決済みでも削除せず solved_by を記録

Position Bankは同一SFENをdedupeし、同一局面の複数回結果は統計として集約する。

## Diagnosisの原因分類

自動分類は断定ではなく `suspected_cause` とする。

- `search_horizon`: shallow/deepで手・評価が大きく変わる
- `evaluation`: 深く読んでも実戦手候補だが、その後の結果と静的評価が系統的に矛盾
- `book`: Book離脱時点ですでに明確に悪い
- `tactical`: 王手・駒取り・詰み周辺で急落
- `mobility`: Activityが高いのに有効手が乏しい反復傾向
- `king_safety`: 玉周辺攻撃密度とSafetyの不整合
- `unknown`: 現行特徴では説明困難。新しいEngine仮説の最重要候補

`unknown` を失敗扱いしない。新しい評価軸を発見する研究対象とする。

## Strength / Independence / Novelty

### Strength

- paired score
- Elo estimate + uncertainty
- fixed-old-version benchmark
- 外部benchmark（毎晩必須ではない）

### Independence

- Book hit率 / Book離脱手数
- 現行版とのmove一致率
- 外部AIとの一致率は測定しても目的関数にはしない

### Novelty

珍しいだけでは加点しない。`valuable-novelty` は次を全て満たす方向で定義する。

- Championまたは既存Bookと異なる選択
- 深い再探索で許容範囲内
- 同種局面で再現性がある、またはその後の実戦成績が良い

## Bookの扱い

BookはExperienceの一部であり、夜間研究全体の中心ではない。

記録するもの:

- Book hit数
- Book使用手数
- Book離脱局面
- 離脱時の総合評価・内訳
- 最終勝敗

Book更新の主信号は離脱時の局面品質とし、最終勝敗だけを全Book手へ配賦する旧方式は新Nightlyでは行わない。Book自動更新は、新しいcredit assignmentが実装・検証されるまで停止する。

## 朝のレポート

必須セクション:

1. `Run integrity`: SHA、対局数、illegal、capability gaps
2. `Experience`: 局数、保存局面、Position Bank追加数
3. `Strength`: Challenger順位、paired score、Elo推定、速度
4. `Diagnosis`: eval-swing / surprise / disagreement / blind-spot 件数
5. `Novelty`: valuable novelty候補
6. `Book`: hit、離脱時品質、最終結果（別表示）
7. `Research findings`: 反復して見つかった弱点
8. `Daytime candidates`: 次に人間と議論すべきEngine/Experience課題

レポートは「次に何を実装するか」を自動決定しない。証拠と候補を提示する。

## 昇格ルール

夜間処理からmainへ自動昇格しない。

朝の採用判断では最低限:

- illegal = 0
- 狙ったDiagnosis問題で改善
- Championとのpaired matchで悪化していない
- 速度低下が許容範囲
- 既存regression suiteを破壊していない
- 外部benchmarkは別軸として記録

を確認する。

## Capability gates

理想仕様を簡易実装でごまかさないため、未実装機能は明示する。

- G1: Champion固定・paired arena・結果集計
- G2: Position Bank形式・抽出・再開局面arena
- G3: per-position evaluation breakdown取得
- G4: shallow/deep disagreement・eval swing抽出
- G5: problem suite自動生成
- G6: Challenger manifest・自動設定候補
- G7: sequential allocation / Elo uncertainty
- G8: Book離脱時credit assignment
- G9: valuable novelty判定
- G10: fixed external benchmark連携

Nightlyをmainへ切り替える前にG1–G5を必須とする。G6以降は欠落をレポートに明示し、順次完成させる。旧Book-only Nightlyを「新Nightly完成」と呼ばない。
