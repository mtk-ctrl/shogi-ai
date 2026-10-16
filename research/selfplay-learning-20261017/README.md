# 自己対局学習の第2回

[結果と限界](RESULTS.md)、[事前計画](PLAN.md)、[確認前の候補選択](selection.json)、[保存hash一覧](publication.json)を参照する。正式Engineへの自動採用はしない。

- 学習コードの固定ref：`20b2b21be25bc3bd56fe423935eb36e78a9a7cd4`。厳密な学習再実行はこの学習前のrefを使う。候補保存後のbranchには学習済みheaderがあるため、それを旧モデルの学習前状態とみなして再起動しない。
- 実戦用の3候補は[measurements.json](measurements.json)の40桁commitで固定。表示名がv2.0.20でも、比較Bは正式v2.0.21で、両者の探索設定を明示して検証している。
- 主な派生物は小さいJSON・モデルをこのbranchに保存。実戦手原本・実バイナリ・派生学習データは月別データReleaseに保存し、Raw/PVは期限付きのままとする。
- 手動で再実行する前に開発ルーターとactive Ruleを読み、現在のrunner、重複依頼、正確なcandidate/baseline/倍率を確認する。学習・速度診断・対局・監査・採否は別の段階である。
