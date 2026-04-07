#!/bin/bash
# OAuth サーバ・Slack ボット・ios-shortcut-api（Siri→Meet）をバックグラウンドで起動する
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
if [[ ! -d .venv ]]; then
  echo "先に: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
source .venv/bin/activate
pkill -f "oauth_server.py" 2>/dev/null || true
pkill -f "slack_bot.py" 2>/dev/null || true
if [[ -f "$ROOT/ios-shortcut-api.pid" ]]; then
  kill "$(cat "$ROOT/ios-shortcut-api.pid")" 2>/dev/null || true
fi
sleep 1
nohup python oauth_server.py >> oauth_server.log 2>&1 &
echo $! > oauth_server.pid
nohup python slack_bot.py >> slack_bot.out 2>&1 &
echo $! > slack_bot.pid
sleep 1
echo "oauth_server PID: $(cat oauth_server.pid)  log: oauth_server.log"
echo "slack_bot    PID: $(cat slack_bot.pid)  log: slack_bot.out / slack_bot.log"
curl -s -S http://127.0.0.1:8888/health && echo " (oauth OK)" || echo "oauth /health に失敗 — ポート 8888 を確認"
echo ""

# ios-shortcut-api（3847）— oauth_server の POST /api/meet がここへプロキシする
IOS_DIR="$ROOT/ios-shortcut-api"
if [[ -d "$IOS_DIR" ]] && [[ -f "$IOS_DIR/package.json" ]]; then
  if [[ ! -d "$IOS_DIR/node_modules" ]]; then
    echo "ios-shortcut-api: node_modules なし → cd ios-shortcut-api && npm install を実行してください（Siri/Meet は未起動）。"
  else
    if command -v lsof &>/dev/null; then
      lsof -ti :3847 | xargs kill -9 2>/dev/null || true
      sleep 1
    fi
    (
      cd "$IOS_DIR" || exit 1
      npm run build
      nohup npm start >> "$ROOT/ios-shortcut-api.log" 2>&1 &
      echo $! > "$ROOT/ios-shortcut-api.pid"
    )
    # Node の bind まで数秒かかることがある
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if curl -sf -m 2 http://127.0.0.1:3847/health >/dev/null 2>&1; then
        echo "ok (ios-shortcut-api OK)"
        break
      fi
      sleep 1
    done
    curl -sf -m 2 http://127.0.0.1:3847/health >/dev/null 2>&1 || echo "ios-shortcut-api /health に失敗 — ポート 3847・.env を確認（ios-shortcut-api.log を参照）"
    echo "ios-shortcut-api PID: $(cat "$ROOT/ios-shortcut-api.pid")  log: ios-shortcut-api.log"
  fi
else
  echo "ios-shortcut-api ディレクトリなし — スキップ"
fi
echo ""
if [[ -f .env ]] && grep -q '^[[:space:]]*NGROK_DOMAIN=' .env 2>/dev/null; then
  echo "ヒント: .env に NGROK_DOMAIN があります。他端末からの OAuth 用に別ターミナルで ./remote_oauth.sh を起動し続けてください。"
fi
echo "他端末から Google 連携: ./start_stack.sh（推奨・bot+ngrok）/ ./remote_oauth.sh / ./remote_oauth_cloudflared.sh → .env の OAUTH_PUBLIC_BASE_URL → REMOTE_SETUP.md"
