# Experience Cache 設計・実装

## 目的

前の対局・前の思考で一度読んだ局面について、次に同じ局面へ到達したときに探索の手掛かりを再利用し、同じ読みを最初から繰り返す時間を減らす。

最終目標は、節約した計算資源をより深い探索へ回すことである。ただし過去の評価値をいきなり正解として扱うと、評価関数変更、探索方式変更、千日手等の履歴依存により誤った枝刈りを起こす危険がある。

そのためv0.0.11では、まず安全なmove-ordering hintだけを再利用するV1を実装した。

## 現在の実装

### 1. 思考内TTとは別の長寿命cache

既存の置換表は `choose()` ごとにgenerationを更新し、1回の思考内だけで使う。

Experience Cacheはそれとは別である。

- `choose()` で消さない
- `usinewgame` で消さない
- 前回以前の思考で得た手だけを参照する
- 現在の思考中に書いたentryは現在の思考では参照しない

これにより、1回の探索内の重複局面はTT、前の手・前の対局・前のプロセスの経験はExperience Cacheという役割分担にした。

### 2. 保存する内容

V1のentryは主に次を持つ。

- `position_key`：`Position::hash_key()`
- `best_move`：その局面で前回有望だった手
- `depth`：その手を得た探索深さ
- generation

評価値、Exact / Lower / UpperのBoundはV1では探索判断に使用しない。

保存対象は、

1. rootで3-ply探索を完了して選んだ手
2. `search_min` / `search_max` を最後まで読み切ったExact nodeのbest move

である。途中cutoffだけで得た手はV1ではExperience Cacheへ保存しない。

### 3. 利用方法

move orderingの優先順位は原則、

1. 現在の思考内TT move
2. Experience Cache move
3. 通常の `MoveOrder::order()`

とする。

Experience Cacheに保存された手が現在の合法手に存在しない場合は無視する。

rootの探索順が変わっても、最終的な同点候補は元の合法手順へ戻してからseed付き乱数を使う。したがって、並べ替えだけで従来の同点選択規則を変えない。

## 固定サイズ

`engine/strategy/experience_cache.h` に131,072 entryの固定サイズtableを実装した。

無制限なmapではなく固定容量とし、スマホでのメモリ使用量を予測可能にする。

- 同じ局面なら深い結果を優先
- 衝突した場合も深い結果を優先
- 同じ深さなら新しい結果へ更新

## 千日手・履歴依存

`position.has_repeated_history()` がtrueの局面ではExperience Cacheを使わない。

V1は評価値を再利用しないため危険は限定的だが、履歴依存局面で盤面hashだけを信用しない方針を維持する。

## 評価設定変更時の安全策

評価設定を変更するとメモリ上のExperience Cacheを全消去する。

さらにファイル保存には設定signatureを付ける。

signatureには少なくとも、

- EvalProfile
- EvalSafety
- EvalPressure
- EvalActivity
- EvalDanger
- 評価関数の各係数・上限
- Experience/search semantics version

を反映する。

設定が一致しない保存ファイルは読み込まない。

これにより、例えばEvalDanger=150時代の経験をEvalDanger=200で無条件に使用しない。

## エンジン再起動後のファイル永続化

ユーザー要望に合わせ、同一プロセス内だけでなくエンジン再起動後にも経験を残す機能まで前倒しした。

USI option：

- `ExperienceCache`：cache利用のON/OFF
- `ExperienceFile`：保存ファイル。初期値 `shogi-ai-experience.bin`

保存タイミングは `gameover`、次の `usinewgame`、`quit` 等である。毎手table全体をディスクへ書くことは避ける。

ファイルはmagic、version、設定signature、entry数、各entryを持つ。

読み込み・書き込みに失敗してもエンジンを停止させない。保存できない環境では通常探索へ戻るfail-open方式である。

Android OEXでは実際の作業ディレクトリがホストアプリ側の起動方法に依存するため、実機で保存ファイルが継続して残る場所は別途確認する。ただし書込不能で対局不能になる設計にはしていない。

## 正しさの検証

`tests/test_experience_cache.py` で以下を自動確認する。

1. cold searchではexperience hitが0
2. 同じプロセスで `usinewgame` 後に同一局面を読むとhitする
3. bestmoveはcold / warmで同じ
4. `quit` で保存ファイルが生成される
5. 新しいエンジンプロセスが保存ファイルを読み、最初の探索からhitする
6. EvalDanger等の設定が違う場合は古いファイルを使用しない
7. ExperienceCacheをOFFにするとprobe/hitが0になる

Focused CI run `37194059219` で成功した。

- same-process warm hits：37
- engine restart後の初回search hits：37

## 性能測定

同じstartposを同じseedで8回繰り返し、cache OFFとONを比較した。初回はcoldとして除外し、2回目以降7回をwarm比較した。

Experience Cache Benchmark run `37193538935`：

- cache OFF：1回あたり 2,029 nodes
- cache ON：1回あたり 967 nodes
- warm 7回合計：14,203 → 6,769 nodes
- **探索node 52.3%削減**
- wall time：292.6ms → 142.8ms
- **約51.2%短縮**
- bestmoveは全8回一致
- cold searchのexperience hitは0
- warm experience hits合計259

この結果から、「前回までに読んだ有望手を先に読むだけ」でも同じ局面ではalpha-beta cutoffが大きく増え、再探索コストを約半分にできることを確認した。

## 実戦対局での検証

同一局面の繰り返し試験だけで標準ONにはせず、Experience Cache ON対OFFの自動対局でも違法手・nodes・hitを確認する。

20局validation workflow：`.github/workflows/experience-cache-match.yml`

## 第2段階：本格再利用

反復深化・時間管理が入った後、entryへ次を加える候補とする。

- 評価値
- Exact / Lower / Upper
- 完了探索深さ

十分な深さ・同一config・履歴安全条件を満たす場合に限り、過去結果を探索windowやTT seedとして利用する。

目標は、前回5-plyまで読んだ局面なら同じ5-plyを全部やり直すのではなく、前回結果を土台に6-ply以降へ計算時間を回すことである。

## 今後の順序

1. Experience Cache V1の自動対局確認
2. 問題がなければ標準ON化
3. Android実機で保存先と再起動後の再利用を確認
4. 反復深化
5. 時間管理・可変深度
6. 静止探索
7. Experience Cache第2段階
