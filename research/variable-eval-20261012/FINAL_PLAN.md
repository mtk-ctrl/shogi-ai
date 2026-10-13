# 最終独立比較 2,400局 事前計画

2026-10-13 13:40 JST。研究候補ATTACK_AVGとUNIFIEDを凍結し、正式採用は行わない。

- ATTACK_AVG: 4e2711f616ce363ab36bbddff25c3d7fcf2aaec8
- UNIFIED: 3fd3c37cc4b83f9645af509e1002837c09f4d5dd
- 正式M: 616e6f258f76642a91f8545c570f92a0dbf71ed4
- 正式Q14: c6311d266717d41cb3b6b84bbe22e870450e6365

各候補×各正式対照600局、3 shard×200局。M seed 2014000000、Q14 seed 2014010000、shardごと+100000、game_offset 0/200/400。go movetime 200、AdaptiveLongThink=true、PositionKnowledge=true、163件同一ファイル、max_plies=300。

最大10runnerを守るため、第一波はATTACK_AVG対M/Q14とUNIFIED対Mの9 lane。完了後にUNIFIED対Q14の3 laneを投入する。他目的runは停止しない。選択データと最終データは合算しない。

ATTACK_AVGは寄与確認でM54.5%/Q1463.5%、UNIFIEDは中間でM59.0%/Q1451.0%だったため選択したが、これは選択用データであり最終強さの証明ではない。多重比較・選択偏りを最終解釈に含める。
