# Daytime Research Backlog

## 位置付け

この文書は **夜間対局システムの実装課題ではなく、日中にオーナーとChatGPTが一つずつ議論・設計・実装する研究課題** を管理する。

夜間は経験生成・診断・登録済み仮説の検証を行う。以下の新しい「考え方」を、夜間処理が勝手に簡易実装して置き換えてはいけない。

## Engine — 評価システム

### E1 Influence（効き・盤面支配）

検討事項:
- 効きの広さと質
- 攻めの効き / 守りの効き
- 重要マスへの効き
- 同一地点の数的優位
- 敵陣・中央・玉周辺の価値差
- AttackMapとの責務分離
- Pressure / Dangerとの二重計上回避

検証:
- 固定局面
- Influence OFF ablation
- Champion paired match
- control-conflict局面での局面別成績

### E2 Coordination（駒の連携・形）

検討事項:
- 相互防御
- 浮き駒・孤立駒
- 玉と守備駒の連結
- 攻撃駒の共同作用
- グラフ表現の必要性

### E3 Mobility / Freedom の拡張

現行Activityは安全な移動先数を中心にしている。以下を別概念として扱うか検討する。
- 有力合法手数
- 拘束駒
- 大駒の通り
- 玉の逃げ道
- 成り余地
- 持ち駒の有効な打ち場所

### E4 Space（空間）

- 安全に使えるマス
- 敵陣への進出余地
- 持ち駒を打てる空間
- 将棋特有の再投入をどう評価するか

### E5 Flexibility / Irreversibility

- 歩突き、桂跳ね、駒打ち、交換による選択肢減少
- 「形を決める」コスト
- 利益との比較方法

### E6 Local superiority

- 戦場の攻守密度
- 攻撃/守備駒の価値合計
- 玉周辺の局所攻守比
- Pressureとの境界

### E7 局面別weight / Phase model

- 序盤・中盤・終盤
- 攻勢・守勢
- 詰みに近い局面
- 固定weightからの移行条件

### E8 評価値の校正

- 評価値と自己対局実勝率の対応
- +100/+300/+500等の勝率曲線
- featureごとの過大/過小評価検出

## Engine — 探索

### S1 探索延長
- 王手
- 玉危険急増
- 戦術的交換
- 評価不安定局面

### S2 move ordering
- Influence/Coordination等の軽量特徴をorderingへ使う価値
- 静的評価との責務分離

### S3 静止探索の拡張
- 現在の対象手が十分か
- 王手・脅威・成り・危険回避の扱い

### S4 時間管理
- 50msを開発基準にしつつ、局面難度に応じた配分
- 長時間時の棋力曲線

### S5 詰み・終盤
- 5-ply MateSearchの次段階
- 詰めろ/必至に近い概念を評価・探索のどこで扱うか

## Experience

### X1 Position Bank
- 類似局面の定義
- dedupe
- 層化抽出
- 長期保存形式

### X2 自分専用問題集
- 敗着候補
- 探索不足
- 評価不足
- 王安全
- Influence
- 終盤
- solved/regressedの履歴

### X3 Book credit assignment
- 離脱時評価を主信号にする方式
- 各Book手への責任配分
- 最終勝敗を補助信号にする強さ
- Book vs Book / Book vs Coreの役割

### X4 ExperienceCache
- 現在の探索経験キャッシュと長期局面学習の違い
- 棋力寄与と過適応

### X5 将来イベント予測
- 数手以内の交換
- 王手
- 成り
- 次に取られる駒
- 玉危険増加

## Benchmark / Independence / Novelty

### B1 内部基準
- Champion vs Challenger
- 固定旧版との長期Elo系列

### B2 外部基準
- やねうら王は教師ではなく物差し
- 固定条件・固定レベル
- 外部戦だけに適応した改善を警戒

### B3 Independence
- Book依存度
- 現行版とのmove一致率
- 外部AI一致率は観測値に留める

### B4 Valuable Novelty
- 珍しい悪手を除外する基準
- 深い再探索
- 再現性
- その後の勝率

## 進め方

原則として一つの仮説について以下を守る。

1. 日中に仮説と責務を議論する。
2. 固定局面で狙った能力を確認する。
3. 実験版をmanifestへ登録する。
4. 夜間にChampionとpaired validationする。
5. Ablationで寄与を確認する。
6. 外部benchmarkは別軸で測る。
7. 採否・理由・次課題をjournal/開発史へ残す。

複数の新概念を一度に本番へ入れ、何が効いたか分からなくすることを避ける。ただし研究上の相互作用を調べるため、単独効果確認後に組合せ実験を行う。
