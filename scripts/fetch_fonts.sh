#!/usr/bin/env bash
# تنزيل الخطوط العربية المستخدمة في الصور (Tajawal من Google Fonts، رخصة OFL).
set -euo pipefail

DEST="$(cd "$(dirname "$0")/.." && pwd)/assets/fonts"
BASE="https://raw.githubusercontent.com/google/fonts/main/ofl/tajawal"

mkdir -p "$DEST"

for VARIANT in Regular Bold ExtraBold; do
  TARGET="$DEST/Tajawal-$VARIANT.ttf"
  if [[ -s "$TARGET" ]]; then
    echo "موجود مسبقًا: Tajawal-$VARIANT.ttf"
    continue
  fi
  echo "تنزيل Tajawal-$VARIANT.ttf ..."
  curl -fsSL -o "$TARGET" "$BASE/Tajawal-$VARIANT.ttf"
done

echo "✅ الخطوط جاهزة في $DEST"
