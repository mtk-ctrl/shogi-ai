# 開発用固定署名

Pixelへ開発版APKを繰り返し上書きインストールするため、GitHub Actionsでは同じ公開テスト鍵で署名する。
本番配布・Playストア公開・正式リリースには絶対に使用しない。

## 目的

GitHub Actionsの通常のdebug署名は実行環境ごとに変わる可能性があるため、APKを更新するたびにAndroid側で署名不一致となり、アンインストールが必要になることがある。
固定テスト署名にすることで、最初の移行後は新APKを「更新」で上書きできるようにする。

## 鍵の扱い

鍵そのものはこのリポジトリに保存しない。
`scripts/make_dev_keystore.sh` が Android Open Source Project の公開 `testkey` を、次のコミットに固定して取得する。

- Repository: `aosp-mirror/platform_build`
- Revision: `045a3d6a3e359633a14853a5a5e1e4f2a11cbdae`
- Files: `target/product/security/testkey.pk8`, `testkey.x509.pem`

取得した証明書のSHA-256を `DEV_CERT_SHA256.txt` と照合してから `dev-signing.p12` を一時生成する。
`dev-signing.p12` はGit管理しない。

## 注意

固定署名へ切り替える最初の1回だけ、従来の別署名APKをアンインストールする必要がある。
その後は同じApplication ID・同じ固定テスト鍵・増加するversionCodeを維持する限り、APKを上書き更新できる。
