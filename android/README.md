# 雲路 KUMOJI Android / OEX

このディレクトリは、雲路（KUMOJI）をAndroid上でShogiDroid2から利用するためのOEXアプリ部分である。

## 最後に作ったAPK：v1.0.1

最新エンジンはKUMOJI v2.0.1である。v2以後はAndroidへダウンロードする必要がなく、新たなAPKは作っていない。オーナーのAndroidには以前のv1が入っている（2026-10-07本人確認）。以下はv1.0.1 APKの記録であり、現在のmainエンジンの表示名ではない。

- アプリ表示名：`雲路 KUMOJI`
- OEX表示名：`雲路 KUMOJI v1.0.1`
- USI名：`KUMOJI v1.0.1`
- package / Application ID：`com.mtkctrl.shogiai`
- native engine：`libshogiai.so`
- CPU：`arm64-v8a`
- minSdk：24
- targetSdk：36
- versionName：`1.0.1`
- versionCode：`10101`

Application IDとnativeファイル名は、旧`shogi-ai` Android版からの更新互換性を維持するため変更しない。

## 構成

エンジン本体の正本は `engine/` と `third_party/yaneuraou/` にある。Android用の `libshogiai.so` はGitHub Actions内でNDKを使って生成し、APKへ格納する。生成済み`.so`や`.apk`はソース管理へコミットしない。

`enginelist.xml` と `ShogiEngineProvider` により、ShogiDroid2へOEXエンジンを公開する。

## 局面知識

採用済みの局面知識はビルド時にエンジンへ内蔵される。OEXホストで外部ファイルを渡せない場合も、同じ採用済み知識を利用できる。

## APK生成

`android/VERSION` の変更を完成版APK生成の明示的な合図とする。

GitHub Actions `Build Android OEX APK` は、ホスト側のルール・探索・評価・詰み・局面知識・Sanitizer検証後、ARM64エンジンとAPKを生成し、固定開発証明書で署名する。

v1.0.1のartifact名：

```text
KUMOJI-v1.0.1-fixed-debug-apk
```

APK名：

```text
KUMOJI-v1.0.1-fixed-debug.apk
```

この固定署名は旧Android版と同じものを使用し、同一Application IDのAPKとして更新可能な状態を維持する。

## 実機確認

APK生成・自動検証後に人が確認する事項は最小限とする。

1. APKをPixelへインストールまたは更新する。
2. `雲路 KUMOJI` アプリの「USI接続テスト」でSUCCESSを確認する。
3. ShogiDroid2のエンジン一覧で `雲路 KUMOJI v1.0.1` を選ぶ。
4. 必要な節目で実対局を行い、起動・着手・時間切れ・終了処理を確認する。

通常の戦略変更ごとに実機確認する必要はなく、自動試験では確認できない完成版の節目だけ行う。
