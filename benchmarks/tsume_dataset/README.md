# 固定詰将棋ベンチセット

やねうら王公式が公開している約500万局面の詰将棋データから、開発用ベンチマークとして固定抽出したSFENである。

- 配布元: `https://yaneuraou.yaneu.com/2020/12/25/christmas-present/`
- 3 / 5 / 7 / 9 / 11手詰めを各1,000問
- 抽出seed: `20261005`
- 抽出方法、元ZIP・元ファイル・抽出ファイルのSHA-256: `manifest.json`
- 再生成: `benchmarks/prepare_tsume_benchmark.py`

約190MBの元ZIPはGitHubへ保存しない。このフォルダには固定比較に必要な5,000問だけを置く。

元データの利用条件については配布元の記載を正とする。
