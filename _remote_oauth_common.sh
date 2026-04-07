# OAuth サーバが起動していることを保証する。
# 前提: カレントディレクトリがプロジェクトルートで、.venv を有効化済み。
ensure_oauth_server_running() {
  if ! curl -s -S --max-time 1 http://127.0.0.1:8888/health >/dev/null 2>&1; then
    echo "oauth_server を起動しています..."
    pkill -f "oauth_server.py" 2>/dev/null || true
    sleep 1
    nohup python oauth_server.py >> oauth_server.log 2>&1 &
    echo $! > oauth_server.pid
    sleep 2
  fi

  if ! curl -s -S --max-time 2 http://127.0.0.1:8888/health >/dev/null 2>&1; then
    echo "oauth_server が起動しません。oauth_server.log を確認してください。"
    return 1
  fi
  return 0
}

# 公開ベース URL とトンネル停止ヒントを表示する。
print_oauth_public_url_instructions() {
  local public_url="$1"
  local stop_hint="$2"
  local CALLBACK="${public_url}/oauth2callback"
  echo ""
  echo "========== 次を .env に設定 =========="
  echo "OAUTH_PUBLIC_BASE_URL=${public_url}"
  echo "======================================"
  echo ""
  echo "Google Cloud Console → OAuth クライアント → 承認済みのリダイレクト URI に追加:"
  echo "  ${CALLBACK}"
  echo ""
  echo "設定後、slack_bot.py / oauth_server.py を再起動してください。"
  echo "$stop_hint"
}
