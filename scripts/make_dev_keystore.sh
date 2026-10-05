#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIGNING="$ROOT/android/signing"
OUT="$SIGNING/dev-signing.p12"
REVISION="045a3d6a3e359633a14853a5a5e1e4f2a11cbdae"
BASE="https://raw.githubusercontent.com/aosp-mirror/platform_build/$REVISION/target/product/security"
EXPECTED="$(tr -d '\r\n' < "$SIGNING/DEV_CERT_SHA256.txt")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "$BASE/testkey.pk8" -o "$TMP/testkey.pk8"
curl -fsSL "$BASE/testkey.x509.pem" -o "$TMP/testkey.x509.pem"

ACTUAL="$(openssl x509 -in "$TMP/testkey.x509.pem" -noout -fingerprint -sha256 \
  | sed 's/.*=//' | tr -d ':' | tr '[:lower:]' '[:upper:]')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "Unexpected AOSP development certificate: $ACTUAL" >&2
  exit 1
fi

openssl pkcs8 -inform DER -nocrypt -in "$TMP/testkey.pk8" -out "$TMP/testkey.pem"
openssl pkcs12 -export \
  -inkey "$TMP/testkey.pem" \
  -in "$TMP/testkey.x509.pem" \
  -name shogi-ai-dev \
  -out "$OUT" \
  -passout pass:shogi-ai-dev >/dev/null 2>&1

echo "$OUT"
