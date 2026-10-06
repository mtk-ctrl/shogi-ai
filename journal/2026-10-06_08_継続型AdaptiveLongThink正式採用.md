# 2026-10-06 継続型AdaptiveLongThink正式採用

200msを通常思考時間とし、必要局面だけ同じ反復深化を最大1秒まで継続するAdaptiveLongThinkを正式採用した。

## 実装

研究runnerの再スタート方式をそのまま製品化せず、SearchControlのsoft deadline到達時に探索状態を見てhard deadlineを延長する方式へ変更した。

- 通常: go movetime 200
- 最大: go movetime 1000相当
- 1局最大10回
- TT・反復深化・PVを保持したまま継続
- 王手、評価急落、iteration評価変化、第一候補変化、depth2未完了、枠期限で発動
- AdaptiveLongThink USI optionは既定true
- usinewgameで回数・前回scoreをリセット

## 100局

run `37452699530`

- ON 59勝 / OFF 38勝 / 3分
- ON得点率 60.5%
- 95%通常近似 50.9%–70.1%
- 違法手0
- 669回発動、平均6.69回/局
- 1手平均応答 ON 248.50ms / OFF 167.69ms

先行の再スタート型は60勝37敗3分、61.5%。継続型でもほぼ同じ効果を再現したため正式採用する。

## 夜間

Nightly Book LearningとNightly Researchも200ms＋AdaptiveLongThinkへ変更する。時間枠を守るためバッチ/局数を縮小する。Diagnosisの50/500ms固定再解析は変更しない。

詳細: `docs/31_AdaptiveLongThink正式採用.md`
