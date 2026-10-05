# 雲路 KUMOJI Android / OEX

このディレクトリは、雲路（KUMOJI）をAndroid上でShogiDroid2から利用するためのOEXアプリ部分である。

## v1.0.1

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

## Opening Book

標準の自前Bookはリポジトリ直下 `shogi-ai-book.tsv` で管理する。

OEXホストからエンジンだけが起動されても同じBookを利用できるよう、ビルド時に標準Bookをエンジンへ内蔵する。実行場所に外部 `shogi-ai-book.tsv` が存在する場合は外部版を優先し、存在しない場合だけ内蔵版へフォールバックする。

## Experience Cache

Experience Cacheは標準ONである。Android上の実際の保存場所・永続性はShogiDroid2側の起動方法に依存する。書き込みできない場合でも探索を停止せず、通常探索へ戻るfail-open方式である。

## APK生成

`android/VERSION` の変更を完成版APK生成の明示的な合図とする。

GitHub Actions `Build Android OEX APK` は、ホスト側のルール・探索・評価・詰み・Opening Book・Sanitizer検証後、ARM64エンジンとAPKを生成し、固定開発証明書で署名する。

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
