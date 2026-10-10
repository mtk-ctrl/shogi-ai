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

現在の正式Engine世代は `KUMOJI v2.0.7` で、実装の正本は `main` である。評価プロファイルBを維持し、本人指定の長考配分訂正を反映した（`docs/36_v2.0.1長考配分.md`）。現在のmain bridgeはQuick CIのFloodgate dry-runで検査する。
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
