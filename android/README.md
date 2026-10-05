# Android / OEX パッケージ

このディレクトリは、`engine/` のルール層・自作戦略を Android 上で ShogiDroid2 から利用するための OEX アプリ部分である。

## 方針

- エンジン本体の正本は `engine/` と `third_party/yaneuraou/`
- Android 用実行ファイル `libshogiai.so` は GitHub Actions 内で NDK を使って生成する
- `.so` や `.apk` はソース管理にはコミットしない
- APK は GitHub Actions の Artifact として取得する

## 現在の構成

- パッケージ名: `com.mtkctrl.shogiai`
- 対応 CPU: `arm64-v8a`
- OEX 表示名: `shogi-ai v0.0.2`
- エンジンファイル名: `libshogiai.so`
- Android 最低 API: 24
- targetSdk: 36

## 実機確認

アプリ単体を開くと「USI接続テスト」ボタンがあり、以下を確認できる。

1. `usi` → `usiok`
2. `isready` → `readyok`
3. `position startpos` + `go` → `bestmove <合法手>`（固定の7六歩ではない）

この単体テストが成功してから ShogiDroid2 との接続確認へ進む。

