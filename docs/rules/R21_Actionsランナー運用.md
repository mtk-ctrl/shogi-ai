---
rule_id: R21
status: active
authority: normative
---

# GitHub Actions runner運用

## 目的
runner使用率ではなく、依頼された目的を最短・最大効率で完了する。

## 固定局数の対局
開始前に現在のActions実行状況と利用可能runner数を確認する。
停止してはいけない有効runが使うrunnerを除き、実際に空いているrunner数へ総局数をできるだけ均等に配分する。

- 原則1 Actions job = 1対局lane。
- 空きrunner数より多いjobを作り、意図的な2巡目待機を作らない。
- 空きrunner数より少ないjobでrunnerを遊ばせない。
- 目標は最後のrunnerの終了時刻を最小化すること。

## 時間枠型Nightly
終了時刻を定めた時間枠型は、固定局数と目的が異なる。具体的な夜間対局の期限はR30を参照する。
空きrunnerは原則最大限使うが、総局数だけを最大化せず、Nightlyで定めたExperience generation / Challenger / Validation / Diagnosis等の役割と状態継続性を守った上で、一晩の有効研究量を最大化する。

未実装フェーズを、runnerを埋める目的だけで別用途に勝手に置換しない。capability gapとして残す。

Book / Experience固有のlane構造はH10で保留中であり、既存workflowをこのRuleだけを理由に変更しない。

## 他workflowを止めてよい場合
runner確保だけを理由に別目的の有効runを停止しない。
停止してよいのは次だけ。
1. 同目的の旧runを修正版・再構成版が完全に置き換える。
2. 新しいrunにより旧runがobsoleteになり、旧結果が不要である。
3. ユーザーが明示的に停止を指示した。

## 起動時報告
run IDを確認したら、同じターンで少なくとも次を報告する。
- 総局数・条件
- 同時実行上限
- 他の有効runが使用中のrunner数
- 今回使うrunner数
- job/shard数と局数配分
- Book / Experience条件
- run ID
- 終了予定時刻

## ETAと結果確認
ETAは最近の同種実測を使い、build・queue・artifact等も含め、最後のrunnerが終わる時刻で見積もる。
run ID確認と同じターンで終了予定時刻に結果確認タイマーを設定する。
未完了なら進捗を確認し、新しいETAへタイマーを更新する。ユーザー指示なしに別対局を追加しない。

結果確認タイマーが発火した時点で、未完了・失敗・aggregate未生成・artifact未取得等により最終結果を報告できない場合は、その回の確認だけで終了しない。
原因と進捗を確認し、安全に修正可能な実行上の問題であれば修正する。そのうえで**5分後の一回限りの結果確認タイマーを必ず再設定**し、最終結果を報告できるまで同じ確認を継続する。
最終結果を報告できた時点で、不要になった結果確認タイマーは停止し、一時Workflow等があれば整理する。
