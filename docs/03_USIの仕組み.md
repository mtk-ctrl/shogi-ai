# USIの仕組み

## USIとは

USI（Universal Shogi Interface）は、将棋GUIと将棋エンジンの間で命令や着手をやり取りするための共通インターフェースである。

この規格があるため、ShogiDroid2などのGUIと、自作エンジンを別々に開発できる。

## 基本的な考え方

GUIはエンジンに対して、

- あなたはUSI対応ですか
- 新しい対局を始めます
- 現在の局面はこれです
- 考えてください

と命令する。

エンジンは、

- 自分の名前
- 準備完了
- 思考情報
- 最終的に選んだ1手

を返す。

## 代表的な通信例

```text
GUI → engine: usi
engine → GUI: id name MyShogiAI
engine → GUI: usiok

GUI → engine: isready
engine → GUI: readyok

GUI → engine: usinewgame

GUI → engine: position startpos moves 7g7f 3c3d
GUI → engine: go

engine → GUI: info score cp 20 nodes 1234
engine → GUI: bestmove 2g2f
```

## 各コマンドの意味

### `usi`

GUIがUSI接続を開始する。

エンジンは自分の情報を返し、最後に `usiok` を返す。

### `isready`

GUIが「対局できる状態か」を確認する。

エンジンは準備ができたら `readyok` を返す。

### `usinewgame`

新しい対局の開始を知らせる。

内部キャッシュ等を必要に応じて初期化する。

### `position`

現在局面をエンジンへ伝える。

例：

```text
position startpos moves 7g7f 3c3d
```

は、初期局面から

- 7g7f
- 3c3d

と進んだ局面を表す。

### `go`

現在局面について思考を開始する命令。

時間条件等が付く場合もある。

### `info`

エンジンが思考途中の情報をGUIへ返す。

評価値、探索ノード数、読み筋などを表示できる。

### `bestmove`

最終的に選んだ着手。

例：

```text
bestmove 2g2f
```

なら、GUIはその手を盤面へ反映する。

## 最初の自作AIで必要なもの

最初の目標は、USIコマンドを受け取り、合法手から1手を選んで `bestmove` を返せること。

この段階では強さは不要である。

重要なのは、

1. ShogiDroid2から局面を受け取れる
2. 自作AIが処理できる
3. 着手を返せる
4. 実際の盤面で1手進む

という一連の経路を完成させること。

## 今後の理解ポイント

USIは通信規格であり、「将棋の強さ」を提供するものではない。

強さを決めるのはエンジン内部の、

- 合法手生成
- 評価関数
- 探索
- 時間配分
- 学習済み評価器

などである。
