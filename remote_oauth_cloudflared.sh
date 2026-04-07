#!/bin/bash
# oauth_server を起動したうえで cloudflared（Quick Tunnel）で 8888 を HTTPS 公開する。
# ngrok の authtoken が不要（Cloudflare アカウント不要の実験用トンネル）。
# 本番・安定運用は ngrok の固定 URL や VPS を推奨。
set -e
cd "$(dirname "$0")"

if ! command -v cloudflared &>/dev/null; then
  echo "cloudflared が見つかりません。次を実行してください: brew install cloudflared"
  exit 1
fi

source .venv/bin/activate
# shellcheck source=/dev/null
source "$(dirname "$0")/_remote_oauth_common.sh"
ensure_oauth_server_running || exit 1

pkill -f "cloudflared tunnel --url http://127.0.0.1:8888" 2>/dev/null || true
sleep 1

: > cloudflared.log
echo "cloudflared Quick Tunnel を起動しています..."
nohup cloudflared tunnel --url http://127.0.0.1:8888 >> cloudflared.log 2>&1 &
echo $! > cloudflared.pid

echo "トンネル URL 取得を待機しています..."
PUBLIC_URL=""
for i in $(seq 1 45); do
  if grep -q "trycloudflare.com" cloudflared.log 2>/dev/null; then
    PUBLIC_URL=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' cloudflared.log | head -1)
    if [[ -n "$PUBLIC_URL" ]]; then
      break
    fi
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo ""
  echo "公開 URL を自動取得できませんでした。tail -80 cloudflared.log を確認してください。"
  exit 1
fi

print_oauth_public_url_instructions "$PUBLIC_URL" "cloudflared 停止: kill \$(cat cloudflared.pid)  （PID: $(cat cloudflared.pid)）"
echo ""
echo "※ Quick Tunnel は実験用で URL が変わりやすいです。安定運用は ngrok 有料や固定ホストを検討してください。"
