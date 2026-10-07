---
rule_id: R60
status: active
authority: normative
---

# Android・APK・リリース

## 通常開発との分離
Android版表示更新、APK生成、Pixel/ShogiDroid2実機確認は通常仕上げに含めない。
ユーザーがAPK・実機確認・完成版化を明示した場合に行う。

## Android更新
実機版を更新するときは、エンジン名、Android `VERSION`、versionName / versionCode、ランチャー表示、OEXエンジン名をまとめて整合させる。
Application ID `com.mtkctrl.shogiai` は互換性維持のため固定する。
versionCodeは更新時に増加させる。

## 完成版全車検
節目の完成版ではQuick CIだけで済ませず、対象release workflowのFull validationとAPK生成・署名・artifactを確認する。
「完成」「APK完成」と報告するのは、対象コミットのworkflowが成功し、release-ready manifestと対象SHAが一致することまで確認した後だけとする。

修正コミットを入れた場合、旧コミットの成功結果を新コミットの完成証明に使わない。

## ShogiDroid2
APK更新後にOEXエンジンのコピーが自動更新されるとは限らない。実機確認時に更新・再コピーの要否を確認する。
