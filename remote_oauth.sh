#!/bin/bash
# oauth_server を起動したうえで ngrok で 8888 を HTTPS 公開し、.env 用の URL を表示する。
# 初回は https://dashboard.ngrok.com/ で authtoken を取得し、
#   ngrok config add-authtoken <トークン>
# を実行してください。
set -e
cd "$(dirname "$0")"

# .env に NGROK_DOMAIN=your-name.ngrok-free.dev とあれば、予約ドメインでトンネルする
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if ! command -v ngrok &>/dev/null; then
  echo "ngrok が見つかりません。次を実行してください: brew install ngrok"
  echo "（authtoken 不要で試す場合: ./remote_oauth_cloudflared.sh）"
  exit 1
fi

if ! ngrok config check >/dev/null 2>&1; then
  echo ""
  echo "【必須】ngrok の authtoken が未設定です。次を一度だけ実行してください:"
  echo "  ngrok config add-authtoken <ダッシュボードのトークン>"
  echo "  取得: https://dashboard.ngrok.com/get-started/your-authtoken"
  echo ""
  echo "設定後に再度 ./remote_oauth.sh を実行してください。"
  echo "（authtoken 不要の代替: ./remote_oauth_cloudflared.sh）"
  exit 1
fi

source .venv/bin/activate
# shellcheck source=/dev/null
source "$(dirname "$0")/_remote_oauth_common.sh"
ensure_oauth_server_running || exit 1

# 既存 ngrok を止める
pkill -f "ngrok http 8888" 2>/dev/null || true
sleep 1

if [[ -n "${NGROK_DOMAIN:-}" ]]; then
  echo "ngrok を起動しています（固定ドメイン: ${NGROK_DOMAIN}）..."
  echo "手動の場合: ngrok http 8888 --domain=${NGROK_DOMAIN}"
  nohup ngrok http 8888 --domain="${NGROK_DOMAIN}" --log=stdout > ngrok.log 2>&1 &
else
  echo "ngrok を起動しています（ランダム URL。固定は .env に NGROK_DOMAIN=... を追加）..."
  echo "手動の場合: ngrok http 8888"
  nohup ngrok http 8888 --log=stdout > ngrok.log 2>&1 &
fi
echo $! > ngrok.pid

# Web インスペクタ (4040) が立ち上がるまで少し待つ
sleep 3

echo "トンネル確立を待機しています..."
PUBLIC_URL=""
for i in $(seq 1 35); do
  PUBLIC_URL=$(python3 << 'PY'
import json, sys, urllib.request
for host in ("127.0.0.1", "localhost"):
    try:
        with urllib.request.urlopen(f"http://{host}:4040/api/tunnels", timeout=3) as r:
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

# API が遅い場合のフォールバック（ngrok ログに url= が出る）
if [[ -z "$PUBLIC_URL" ]] && grep -q 'url=https://' ngrok.log 2>/dev/null; then
  PUBLIC_URL=$(grep -oE 'url=https://[^[:space:]]+' ngrok.log | tail -1 | sed 's/^url=//')
fi

if [[ -z "$PUBLIC_URL" ]]; then
  echo ""
  echo "公開 URL を自動取得できませんでした。"
  if grep -q "ERR_NGROK_4018\|authtoken" ngrok.log 2>/dev/null; then
    echo ""
    echo "【必須】ngrok に無料登録し、ターミナルで次を一度だけ実行してください:"
    echo "  ngrok config add-authtoken <ダッシュボードのトークン>"
    echo "  取得: https://dashboard.ngrok.com/get-started/your-authtoken"
    echo ""
  fi
  echo "そのほか: http://127.0.0.1:4040 を開く / tail -50 ngrok.log"
  exit 1
fi

print_oauth_public_url_instructions "$PUBLIC_URL" "ngrok 停止: kill \$(cat ngrok.pid)  （PID: $(cat ngrok.pid)）"
