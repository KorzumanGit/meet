#!/bin/bash
# ios-shortcut-api（既定ポート 3847）を ngrok で HTTPS 公開する。
# 先に別ターミナルで npm start などを実行して API を起動しておくこと。
set -e
cd "$(dirname "$0")"

PORT="${PORT:-3847}"

if ! command -v ngrok &>/dev/null; then
  echo "ngrok をインストールしてください: brew install ngrok"
  exit 1
fi
if ! ngrok config check >/dev/null 2>&1; then
  echo "ngrok config add-authtoken <トークン> を実行してください。"
  echo "https://dashboard.ngrok.com/get-started/your-authtoken"
  exit 1
fi

if ! curl -s -S --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "警告: http://127.0.0.1:${PORT}/health に応答がありません。先に npm start で API を起動してください。"
fi

pkill -f "ngrok http ${PORT}" 2>/dev/null || true
sleep 1

nohup ngrok http "${PORT}" --log=stdout > ngrok-api.log 2>&1 &
echo $! > ngrok-api.pid
echo "ngrok 起動 PID: $(cat ngrok-api.pid)"
echo "ログ: tail -f ngrok-api.log"
echo ""
echo "トンネル URL 取得を待機..."
PUBLIC_URL=""
for i in $(seq 1 25); do
  PUBLIC_URL=$(python3 << 'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as r:
        d = json.load(r)
    for t in d.get("tunnels", []):
        u = t.get("public_url", "")
        if u.startswith("https://"):
            print(u)
            sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
)
  if [[ -n "$PUBLIC_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "URL を取得できませんでした。http://127.0.0.1:4040 または ngrok-api.log を確認してください。"
  exit 1
fi

echo ""
echo "========== iPhone ショートカットの URL に使う =========="
echo "${PUBLIC_URL}/api/meet"
echo "======================================================"
echo ""
echo "停止: kill \$(cat ngrok-api.pid)"
