#!/bin/bash
# oauth_server + slack_bot + ios-shortcut-api（3847）を起動し、ngrok が使えるなら HTTPS トンネルも張る（ターミナル1本）。
# ngrok→8888 の URL で POST /api/meet が Node に届く（oauth_server がプロキシ）。
# .env に NGROK_DOMAIN と OAUTH_PUBLIC_BASE_URL を書いておくと固定ドメインでトンネルします。
set -e
cd "$(dirname "$0")"

./start_services.sh

if ! command -v ngrok &>/dev/null; then
  echo ""
  echo "ngrok が未インストールです。他端末から OAuth が必要なら: brew install ngrok → authtoken → ./remote_oauth.sh"
  exit 0
fi

if ! ngrok config check >/dev/null 2>&1; then
  echo ""
  echo "【注意】ngrok の authtoken が未設定です。他端末から Google 連携するには:"
  echo "  ngrok config add-authtoken <トークン>"
  echo "その後 ./remote_oauth.sh または ./start_stack.sh を再実行。"
  echo "（authtoken 不要の代替: ./remote_oauth_cloudflared.sh）"
  exit 0
fi

echo ""
echo "=== ngrok トンネル（Ctrl+C では止まりません。停止は kill \$(cat ngrok.pid)）==="
./remote_oauth.sh
