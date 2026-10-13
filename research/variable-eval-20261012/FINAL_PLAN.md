# 最終独立比較 2,400局 事前計画

2026-10-13 13:40 JST。研究候補ATTACK_AVGとUNIFIEDを凍結し、正式採用は行わない。

- ATTACK_AVG: 4e2711f616ce363ab36bbddff25c3d7fcf2aaec8
- UNIFIED: 3fd3c37cc4b83f9645af509e1002837c09f4d5dd
- 正式M: 616e6f258f76642a91f8545c570f92a0dbf71ed4
- 正式Q14: c6311d266717d41cb3b6b84bbe22e870450e6365

各候補×各正式対照600局、3 shard×200局。M seed 2014000000、Q14 seed 2014010000、shardごと+100000、game_offset 0/200/400。go movetime 200、AdaptiveLongThink=true、PositionKnowledge=true、163件同一ファイル、max_plies=300。

最大10runnerを守るため、第一波はATTACK_AVG対M/Q14とUNIFIED対Mの9 lane。完了後にUNIFIED対Q14の3 laneを投入する。他目的runは停止しない。選択データと最終データは合算しない。

ATTACK_AVGは寄与確認でM54.5%/Q1463.5%、UNIFIEDは中間でM59.0%/Q1451.0%だったため選択したが、これは選択用データであり最終強さの証明ではない。多重比較・選択偏りを最終解釈に含める。


## 未起動分のrunner配分更新（2026-10-13 14:46 JST）

先発3比較は13:36頃に3shard×200局で実開始済みで変更しない。残るUNIFIED対正式Q14の600局は未依頼・未起動のため、先発終了後に空く10runnerへ10shard×60局で均等配分する。最終対局の勝敗・途中成績は閲覧せず、この運用変更を事前固定する。候補・相手・総局数600・時間・知識・採否基準は不変。

seedは2014010000＋i×100000（i=0…9）、game_offset=60×i。全600局先後300:300。shard数の変更により元ATTACK_AVG対Q14と完全に同じseed列・局数配分ではなくなるため、候補間の差を完全な対応標本として扱わない。

直近同条件100局6laneの実測58.9～62.9分から先発200局は最大約126分＋集計、15:45頃確認。未起動分60局は最大約38分＋build/集計、全独立比較は16:30頃見込み。先発未終了や別目的runがある場合は空きrunner数を再確認し10を超えず同じタスクを更新する。意図的に上限を超える待機jobは作らない。

## 120分上限による失敗と再実行計画（2026-10-13 15:41 JST）

先発3 runは、`engine-match.yml` の対局job上限 `timeout-minutes: 120` に達した。8/9 shardが開始約120分で `The operation was canceled`、1 shardのみ完了し、3 runともaggregateはskippedとなった。コード・固定ref・対局条件の失敗ではなく、200局/shardが上限に対して余裕不足だったことが直接原因である。

失敗波は部分完了を含めて最終推定へ合算しない。Issues #247〜#249を再実行せず、全4比較を未使用seedで再登録する。復旧条件は候補・対照・総局数600・200ms・長考ON・知識163件ON・maxplies300を維持し、各比較を5 shard×120局へ変更する。

- M対照のbase seed: 2114000000
- Q14対照のbase seed: 2114010000
- shard seed: base + i×100000（i=0…4）
- game_offset: 0 / 120 / 240 / 360 / 480
- 第1波: ATTACK_AVG対M/Q14（5+5=10 lane）
- 第2波: UNIFIED対M/Q14（5+5=10 lane）

復旧request_idは `ve31-20261013-final-r1-*` とし、旧requestと区別する。各120局は直近実測から約71〜76分＋build/aggregateを見込む。各波の終了後にraw・集計・着手archiveを監査してから次波へ進む。
