#!/usr/bin/env bash
# 指針第2条（SingletonLock 回避）: 自動化ブラウザ用の一時ユーザデータディレクトリを発行する。
# 既存の Chrome プロフィールと衝突しないよう、毎回ユニークなパスを使う。
set -euo pipefail

PROFILE_DIR="${TMPDIR:-/tmp}/cline-chrome-$(date +%s)-$RANDOM"
mkdir -p "$PROFILE_DIR"
export CLINE_CHROME_USER_DATA_DIR="$PROFILE_DIR"

echo "=== 環境変数（このシェルで source するか export をコピー）==="
echo "export CLINE_CHROME_USER_DATA_DIR=\"$PROFILE_DIR\""
echo ""
echo "=== Google Chrome (macOS) 例 ==="
echo "open -na 'Google Chrome' --args --user-data-dir=\"$PROFILE_DIR\" --no-first-run --disable-session-crashed-bubble --disable-infobars \"\$URL\""
echo ""
echo "=== Chromium (Linux) 例 ==="
echo "chromium-browser --user-data-dir=\"$PROFILE_DIR\" --no-first-run \"\$URL\""
echo ""
echo "=== 終了後に一時ディレクトリを削除（任意）==="
echo "rm -rf \"$PROFILE_DIR\""
