# 2026-10-03 Android OEX化とAPK自動ビルド

## 目的

最小USIエンジン `engine/main.cpp` を、Pixel上で動かせるAndroidアプリとしてパッケージ化し、ShogiDroid2から利用するためのOEX構成を作る。

今回の到達点は、GitHub上のソースコードからPixel向けAPKを自動生成し、実機Pixel上で自作エンジンがUSI通信できることまで確認することである。

## 実装したもの

### Android/OEXアプリ

`android/app/` を追加し、以下を実装した。

- パッケージ名：`com.mtkctrl.shogiai`
- OEXエンジン名：`shogi-ai v0.0.1`
- エンジンファイル名：`libshogiai.so`
- 対応CPU：`arm64-v8a`
- `intent.shogi.provider.ENGINE` を宣言
- `enginelist.xml` でエンジン情報を公開
- `ShogiEngineProvider` からAndroidのnative library領域にあるエンジンを提供

### 単体USIテスト画面

OEXアプリ自体を起動すると「USI接続テスト」ボタンを表示する。

ボタンを押すと、アプリ内の `libshogiai.so` を起動して次の通信を行う。

1. `usi` → `usiok`
2. `isready` → `readyok`
3. `position startpos`
4. `go` → `bestmove 7g7f`

これにより、ShogiDroid2との接続前に「Android上で自作エンジンそのものが起動するか」を切り分けられるようにした。

## 自動ビルド

`.github/workflows/android-apk.yml` を追加した。

GitHub Actionsで以下を自動実行する。

1. ソースコード取得
2. Java 17準備
3. Android SDK / NDK準備
4. `engine/main.cpp` をAndroid ARM64向けにコンパイル
5. `libshogiai.so` をOEXアプリへ組み込み
6. debug APKを作成
7. APKをActions Artifactとして保存

ビルド成果物 `.so` / `.apk` はGitリポジトリにはコミットしない。

## ビルド時のトラブルと解決

### 1回目

`android-actions/setup-android@v3` が、現在のAndroid SDKでは廃止されている古い `tools` パッケージを取得しようとして失敗した。

対応：このActionを外し、GitHub Actionsランナーに既に入っているAndroid SDKを直接使う方式へ変更した。

### 2回目

Android SDK自体は存在したが、`sdkmanager` がPATHに入っておらず `command not found` になった。

対応：`$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager` を明示的に指定した。

### 3回目

全工程成功。

- Android SDK / NDK準備：成功
- C++ → ARM64エンジン変換：成功
- Android APKビルド：成功
- Artifactアップロード：成功

GitHub Actions Run ID：`37112200174`
Artifact名：`shogi-ai-v0.0.1-debug-apk`

## 生成物

生成APK：`shogi-ai-v0.0.1-debug.apk`

このAPKには、現時点の最小USIエンジンが含まれている。

## Pixel実機確認

2026-10-03、PixelへAPKをインストールし、`shogi-ai OEX` アプリを起動した。

「USI接続テスト」を実行し、実機画面上で以下を確認した。

- `usi` に対して `id name shogi-ai v0.0.1` / `usiok`
- `isready` に対して `readyok`
- `position startpos` を受理
- `go` に対して `bestmove 7g7f`
- 最終表示：`SUCCESS: bestmove 7g7f`

これにより、自作C++エンジン `libshogiai.so` がPixel上で実行可能であり、USI通信も成立することを確認できた。

## 次の確認

次はShogiDroid2との実接続を確認する。

1. ShogiDroid2をインストールする
2. ShogiDroid2が `shogi-ai v0.0.1` をOEXエンジンとして認識する
3. 実際の対局を開始する
4. 初期局面から7六歩を盤上で指すことを確認する

ここまで成功すればPhase 0「自作AIがスマホ上で1手指す」を達成したことになる。
