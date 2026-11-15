# Floodgate接続基盤

## 目的

雲路 KUMOJI の外部棋力を継続的に測る到達目標として、コンピュータ将棋対局場 Floodgate への出場を可能にする。

この段階では「実際に対局へ参加すること」ではなく、現行エンジンの評価・探索を変更せず、Floodgateへ安全に接続できる外付け基盤を完成させる。

## 対象

- 対局場: Floodgate
- 公式: https://wdoor.c.u-tokyo.ac.jp/shogi/
- 接続: CSA TCP/IP protocol
- Host: `wdoor.c.u-tokyo.ac.jp`
- Port: `4081`
- 標準対局名: `floodgate-300-10F`
- 時間: 初期300秒、1手ごとに10秒加算

Floodgateの仕様は変更され得るため、実参戦前に公式ページを再確認する。

## 構成

```
Floodgate
    │ CSA
    ▼
tools/floodgate/client.py
    │ USI
    ▼
雲路 KUMOJI
```

エンジン本体にはFloodgate固有処理を入れない。

接続層の責務は次のとおり。

1. CSAのログイン、Game_Summary、AGREE、START、終局処理
2. CSA指し手とUSI指し手の相互変換
3. Floodgateが返す消費時間 `Tn` の追跡
4. KUMOJIへ `btime/wtime` を渡す
5. 対局結果の外部対局ログへの保存

合法手判定と将棋ルールは、従来どおり雲路のルール層とサーバを正とする。

## Floodgateに合わせる終局・引き分けルール

Floodgateの `floodgate-300-10F` では、対局記録に `Max_Moves:512` が設定される。

接続時は次を基準にする。

- 通常の4回同一局面による千日手: 引き分け
- 連続王手の千日手: 王手を続けた側の負け
- 512手に到達して未終局: 引き分け
- 入玉: 27点法の宣言勝ち
  - 先手は28点以上
  - 後手は27点以上
  - 玉が敵陣3段目以内
  - 敵陣3段目以内の自駒が玉を除いて10枚以上
  - 玉が王手されていない
  - 大駒5点、小駒1点。対象は持ち駒と敵陣3段目以内の自駒
- 入玉条件を満たす場合は引き分けではなく `%KACHI` による勝ち

KUMOJIのルール層は既に `EKR_27_POINT` を使用し、4回同一局面と連続王手千日手も判定する。

実対局ではFloodgateサーバを最終的な終局判定の正とする。接続bridgeも相手の着手で4回同一局面または最大512手に達した場合、次の手を送らずサーバの終局通知を待つ。

## 300+10Fの時計

KUMOJIはUSIの `btime/wtime/binc/winc/byoyomi` を解釈できる。

ただし現在の時間配分式はincrementの一部をその着手で使用できる予算として扱うため、Floodgate接続層から未来の10秒を `binc/winc` として先に渡さない。

代わりに、

1. サーバが着手を `,Tn` 付きで返す
2. 実消費時間を残り時間から引く
3. その着手で得た10秒を残り時間へ加える
4. 次の思考時に更新後の `btime/wtime` を渡す

という順にする。

これにより、まだ得ていないincrementを使って時間切れになる危険を避ける。

## 雲路自身の評価値・思考時間の記録（2026-11-15追加）

初参戦（journal/2026-11-15_02）では指し手しか残らず、雲路の評価値を後から見られなかった。オーナーの指示により次を記録する。

- 結果ログ（jsonl）の `our_search` に、雲路の各手の最終 `info`（深さ・評価値・読み筋・節点数）、実測の思考時間 `wall_ms`、その時点の残り時間を残す。`moves_csa_timed` にはサーバが返した全着手と消費秒を残す。
- `--send-eval` を付けると、雲路の評価値を先手から見た値に直し、Floodgateの着手コメント（`,'* 値`）として送る。公開棋譜に評価値が載る。詰みの読み切りは±30000で送る。
- 記録するのは雲路自身の探索結果だけで、相手の評価値は取り込まない（R50）。接続層の変更であり、雲路本体の探索・評価は変えない。

## Floodgate専用の読み時間（2026-11-15追加、オーナー指示）

初参戦では31手すべてを10秒で指し、持ち時間300秒が手つかずだった（本体の配分が「残り÷30」で、加算10秒と釣り合って減らない）。Floodgateに限り、接続層で読み時間を決める。**自己対局・比較対局・梯子では使わない。雲路本体の探索・評価・時間配分は変えない。**

実装は `tools/floodgate/timeplan.py`、有効化は `client.py --time-plan`。接続層が `go movetime 上限` を送り、雲路の途中経過（info）を見て `stop` を送る。

| 段階 | 自分の手数 | 基本の時間（300秒＋10秒の場合） |
|---|---|---|
| 序盤 | 1〜8手目 | 5秒 |
| 中盤 | 9〜40手目 | 8秒＋残りの1/20（最初は約23〜25秒） |
| 終盤 | 41手目以降 | 8秒＋残りの1/30 |
| 残り30秒未満 | — | 8秒のみ、延長なし |

- 縮める: 最善手が読みの深さ4回続けて同じで評価値もほぼ動かなければ、基本の1/3で指す。
- 伸ばす: 最善手が直前に変わった、または評価値が100以上落ちたときは、基本の3倍（かつ残りの1/5＋8秒）まで読む。
- 自分の勝ちの詰みを読み切ったらすぐ指す。どの場合も残り時間−3秒を超えない。
- 各手の段階・基本時間・止めた理由は結果ログの `our_search` に残る。
- 持ち時間が加算つきでない対局では従来どおり（`btime/wtime` を渡す）。

## 常時参加（2026-11-15開始）

- `tools/floodgate/continuous.json` の `enabled` が true のとき、mainの雲路をビルドして `session_minutes`（既定210分）のあいだ続けて対局する。時間を過ぎたら新しい対局を始めず、対局中の1局を終えて終了する。
- **次の回は自分で起動する（連鎖、`tools/floodgate/chain.py`）。** 各回の最後に最新のmainの `continuous.json` を読み、続けてよければ `floodgate.yml` を `workflow_dispatch`（mode=live、continuous=yes、chained=true）で起動する。前の回が終わるまで `concurrency` で待つので、同時に動く実参戦は1本だけ。連鎖で起動した回はリハーサルを省く（空きが約4分短くなる。ビルド時の単体試験と時計確認は毎回行う）。
  - 成功したら次を起動する。失敗（ビルド失敗を含む）なら最大3回まで再起動し、4回続けて失敗したら止める。
  - 取り消し（cancel）では連鎖しない。
  - `enabled` が false、または次の回が `pause_dates_jst` の日に掛かるなら起動しない。
- **定期起動（毎時17分・47分）は予備**として残す。連鎖が切れたとき（手動の1回だけの実参戦が終わった後など）に再開させる。**GitHubの定期起動は遅れたり飛ばされたりする**（2026-11-15は設定直後の10:47・11:17・11:47の3回が動かなかった。journal/2026-11-15_04）ため、定期起動だけに頼らない。
- 始めるとき（連鎖の開始）: Actionsの `floodgate.yml` を mode=live、continuous=yes、confirm_live=LIVE で起動する。定期起動が動いた場合も同じ連鎖になる。
- 止めるとき: `continuous.json` の `enabled` を false にする（次の連鎖から止まる）。すぐ止めるなら実行中のrunを取り消す。`pause_dates_jst` の日は参加しない（2026-12-06はFloodgateの計画停止）。
- 連鎖の配線確認: continuous=selftest（probeを1回だけ連鎖させる。Floodgateへ接続しない）。
- 設定: `PositionKnowledge=true`、`OpeningRandomNonLance=false`（無作為な初手を切る）、`--send-eval`、`--time-plan`。
- 接続の失敗が続けて3回起きたら、その回は失敗で終わる。
- 結果は各runの成果物（90日）とログの `FLOODGATE_RESULT`／`FLOODGATE_MOVE`／`FLOODGATE_CHAIN` 行、Floodgateの公開棋譜に残る。

## 外部対局と学習の分離

FloodgateはR50どおり「教師」ではなく「物差し」として扱う。
相手の評価値・PV・候補手を評価関数学習の教師へ自動投入しない。

外部AI対局の雲路自身の探索結果を局面知識の候補に含める出所判断はR50に従う。局面知識の新候補を正式採用・自動更新するかは別途判断する。

## 秘密情報

FloodgateのCSAモードは対局名とtrip文字列をパスワード欄へ渡す。

tripはGitHubへ保存しない。環境変数 `FLOODGATE_TRIP` だけから読む。

また、CSA接続ではパスワード文字列の秘匿性を前提にしない。tripには他サービスで使うパスワードや個人情報を流用しない。

## 安全装置

`client.py` は既定でネットワークへ接続しない。

```bash
python3 tools/floodgate/client.py --engine build/shogi-ai
```

これはUSI起動、option適用、ready確認だけを行うdry-runである。

実際に接続するには、環境変数を設定したうえで `--live` を明示する必要がある。

```bash
export FLOODGATE_TRIP='unique-non-sensitive-trip'
python3 tools/floodgate/client.py \
  --engine build/shogi-ai \
  --username KUMOJI \
  --games 1 \
  --live
```

複数局を指定した場合も、CSAモードの運用に合わせて1局ごとにTCP接続を張り直す。

## GitHubのEngine世代との接続

Floodgate接続基盤そのものはmain側のインフラとして維持し、対局に使うKUMOJIエンジンは必要に応じbranch / tag / commitで識別できるようにする。
Engine世代ごとにFloodgateコードを複製しない。

以前の `Floodgate Generation Compatibility` workflowはworkflow整理時に `docs/archive/workflows/2026-10-07/floodgate-generation-compat.yml` へ退役した。
そのarchiveに残る `research/evaluation-v2-challenger` は旧研究refであり、現行参照先には使わない。

現在の正式Engine世代・M型重み・G型駒価値・成熟度の計測方式は `docs/現行エンジン仕様.md` に集約している。実装の正本はmainであり、接続基盤はQuick CIのFloodgate dry-runで検査する。
別世代との互換性を改めて検証する必要が生じた場合は、R15に従い既存基盤で自然に扱えるか確認し、必要なら専用workflowを再設計する。

実対局ログにはEngineの `id name`、適用option、実行バイナリSHA-256等を残し、表示versionだけでEngine世代を判定しない。

## 実参戦時の手順

実参戦を行うときだけ次を実施する。

1. mainの採用版をhost向けにビルド
2. Floodgate公式ページの接続先・対局名・時間ルールを再確認
3. dry-run成功を確認
4. 使い捨て可能な非機密tripを環境変数へ設定
5. まず1局だけ `--live --games 1`
6. 時間切れ、違法手、切断、終局処理、ログを確認
7. 問題がなければ15局程度以上を蓄積し、初回レーティングを取得

## 完了基準

接続基盤の完了は次で判定する。

- CSA/USIの通常手、成り、駒打ち変換を単体試験できる
- Game_Summaryの300秒+10秒incrementを解釈できる
- サーバ報告の消費時間から時計を更新できる
- 使用した局面知識の版・内容ハッシュ・件数を記録できる。外部対局の雲路自身の探索結果は知識候補の対象とする（R50）
- `--live` なしではネット接続しない
- tripをコード・設定ファイル・GitHubへ保存しない
- CIでFloodgate関連テストを実行する

実際のFloodgateサーバへのログイン・初対局・レーティング取得は、接続基盤完成後の別マイルストーンとする。
