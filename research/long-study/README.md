# 長考分析・研究記録の共通データ集

2026-10-26、本人の「これまでの長考分析は以前の長考分析のデータに加えておいてください」に対応。以前の研究とNNUE各世代の研究を、一緒に取り出して再利用できる共通入口へ追加した。

原本は[月別データRelease](https://github.com/mtk-ctrl/shogi-ai/releases/tag/records-2026-10-01)で保持する。既存原本の上書きや全履歴の再アップロードはせず、出所とSHAを持つ参照で統合した。

## 収録内容

| 研究群 | 観測数 |
|---|---:|
| 以前の長考（opening20、timebox40の3回、research10、NN不一致30） | 180 |
| 標準NNUE・3世代 | 120 |
| NNUE補正・5世代 | 200 |
| 修正版NNUE補正・5世代 | 200 |
| **長考群の計** | **700** |
| 以前の60秒研究（反復観測を含む） | 91 |
| 短時間の接続検証 | 40 |
| 対局後の診断 | 232 |
| 追加反証 | 16 |
| **研究観測の総数** | **1,079** |

対象は索引に列挙した16原本群・24Release資産・29レコード群。過去の全workflow成果物を網羅したとの主張ではない。
件数は観測レコード数であり、ユニーク局面数・探索回数・採用教師数とは異なる。
同一局面の別条件・再研究は残し、累積checkpointのコピーはcycleごとに最終bundleだけを参照して二重計上を避けた。

## 取り出す方法

- [出所・条件・世代・SHA・採否集計の索引](catalog-20261026.json)
- [原本照合付きの一括読出し](export_observations.py)

```sh
python research/long-study/export_observations.py \
  --cache /tmp/kumoji-study-cache \
  --output /tmp/kumoji-study-observations.jsonl \
  --download
```

Python標準ライブラリのみ。初回の原本取得は805,488,974 bytes（約0.81 GB）。連結bundleと作業ファイル用の空き容量も必要。
各行の `record` に元の全観測を保持し、`observation_id / group_id / record_index` で出所をたどる。catalogには元asset・bundle内member・JSON pointer・条件・SHAがある。圧縮ファイルの中の位置は展開後の配列位置である。

同じ局面の判定は `position_key / history_key / case.source / position_ref` 等の原形式に沿って行う。観測IDは局面IDではない。反復履歴や研究条件の違いを勝手に同一化しない。

## 学習に使うとき

- 採用されなかった研究、不確実な比較、打切りも保存する。長考時間だけを根拠に正解ラベルへ変えない。
- 修正版の学習/検証区分と原局出所を保持。古い記録で群が不明なら不明のまま残す。
- 新しい実験用に選ぶ際は、同一原局・派生局面の学習/検証混入と、採否基準の互換性を再確認する。
- 旧correctionの200例をrepairedへ移行した際の再採否は、元checkpointのbootstrap provenanceと区別して読む。
- MCTSラベルは長考観測数へ混ぜない。元checkpointに棋譜・モデルとともに保持されている。

今回実装したのは保存・参照の統合であり、学習器への自動投入や正式な採用知識の更新ではない。

## 保存検証

24資産のAPI digestとbytes、NNUE4最終bundleのpart/連結SHAおよび内部全1,824ファイルのSHAが一致した。
読出しスクリプトの1,079行を、別経路で原本から組み立てたJSONLとbyte単位で照合した。
出力は5,328,530 bytes、SHA256 `0ed369e563f1575d013c736eef1de1966ab76a8144a952b09fb4cec2ce0544cc`。
保存一致の検証は、研究結論の正しさや棋力向上の証明とは別である。

比較実験の進め方は[判断記録](../../docs/decisions/2026-10-26_長考分析の統合と比較実験方針.md)を参照。
