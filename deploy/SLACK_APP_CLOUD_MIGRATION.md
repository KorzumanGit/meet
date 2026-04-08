# ngrok 廃止 → `https://meet.humbull.co` 一本化（Slack アプリ設定）

## 前提（このリポジトリのボット）

- `slack_bot.py` は **Socket Mode**（`SLACK_APP_TOKEN` / `SocketModeHandler`）を使用している。**イベントは主に WebSocket で受信**し、**必ずしもパブリック HTTP の Request URL を要しない**構成です。
- それでも **過去に ngrok URL を登録した箇所**が残っていると、古い URL への誘導や検証失敗の原因になるため、**api.slack.com 上で ngrok を含む文字列をすべて洗い出して置換または削除**してください。

---

## 1. api.slack.com で確認する場所（チェックリスト）

アプリを選択: **https://api.slack.com/apps** → 対象アプリ

| # | 画面（左メニュー / タブ） | 確認内容 |
|---|---------------------------|----------|
| 1 | **Event Subscriptions** | **Request URL** に `ngrok` / 旧ドメインがないか。**Socket Mode ON かつ Bolt Socket Mode のみ**なら、Request URL は未使用・空でも動くことが多いが、**残存するなら削除または `https://meet.humbull.co/...` に変更**（実際に HTTP エンドポイントを用意する場合のみ）。 |
| 2 | **Interactivity & Shortcuts** | **Request URL** に ngrok がないか。インタラクティブ機能を使っていない場合は OFF または URL 空でよい。 |
| 3 | **Slash Commands** | **各コマンド**の **Request URL**（コマンドごと）。未使用ならコマンド自体を削除するか URL を更新。 |
| 4 | **OAuth & Permissions** | **Redirect URLs**（Slack の OAuth インストール用。通常は `https://hooks.slack.com/...` 系ではなく、アプリが独自に指定した URL）。ngrok があれば本番 URL に。 |
| 5 | **App Home**（該当時） | カスタムタブやメッセージに埋め込んだ URL はコード／管理画面の両方。 |
| 6 | **Incoming Webhooks** | 有効なら Webhook URL は Slack 側発行のため ngrok ではないことが多い。 |
| 7 | **Workflow Steps** / **Custom Steps** | ステップで外部 URL を指定している場合。 |
| 8 | **Enterprise** 系 | 組織ポリシーで別 URL があれば同様。 |

**検索のコツ:** ブラウザでアプリ設定ページを開き、`Ctrl+F` / `Cmd+F` で `ngrok` を検索。

---

## 2. App Manifest の更新案（Socket Mode 例）

リポジトリ内にマニフェストファイルは**同梱していない**ため、**既にエクスポートした JSON/YAML をお持ちの場合**は、テキストエディタで **`ngrok` を含む URL をすべて**次に置換してください。

- **ベース URL:** `https://meet.humbull.co`  
- **OAuth コールバック（Google 用・参考）:** `https://meet.humbull.co/oauth2callback`  
  （※これは **Google Cloud Console** の OAuth クライアント設定。Slack マニフェストの `redirect_urls` は **Slack アプリインストール用**で別物です。）

### 置換の例（概念）

```yaml
# 例: どこかにあった ngrok を meet に
# BEFORE: https://xxxx.ngrok-free.app/slack/events
# AFTER:   https://meet.humbull.co/slack/events   # ← 実際にそのパスで受けるサーバがある場合のみ
```

**Socket Mode 利用時**は、マニフェストの `settings.socket_mode_enabled` が `true` であれば、`event_subscriptions.request_url` は空または省略可能なことが多いです（Slack のスキーマバージョンに依存）。

### サンプル JSON 断片（新規作成ではなく「置換用」の参考）

```json
{
  "display_information": {
    "name": "meet-bot"
  },
  "features": {
    "bot_user": {
      "display_name": "meet",
      "always_online": false
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": ["chat:write", "im:history", "channels:history", "files:read"]
    }
  },
  "settings": {
    "socket_mode_enabled": true,
    "event_subscriptions": {
      "bot_events": ["message.im", "message.channels"]
    }
  }
}
```

実際のスコープ・イベントは **現在の本番アプリに合わせて**ください。上書き前に **Manifest をエクスポートしてバックアップ**を取ってください。

---

## 3. ローカル環境の安全な停止（競合防止）

Mac の `meet/` で:

```bash
cd /path/to/meet
docker compose down
```

**ngrok / cloudflared を使っていた場合:**

```bash
# プロセス例（PID ファイルがあれば）
kill "$(cat ngrok.pid)" 2>/dev/null || true
pkill -f "ngrok http" 2>/dev/null || true
```

**Python を直接起動していた場合:**

```bash
pkill -f "python oauth_server.py" 2>/dev/null || true
pkill -f "python slack_bot.py" 2>/dev/null || true
```

- **クラウド上だけ**で動かすなら、**ローカルでは `slack_bot` / `oauth_server` を起動しない**（同じ Bot Token / App Token で二重接続すると、Socket Mode の接続が競合する可能性があります）。

---

## 4. 最終確認：クラウド上のログ

**VM に SSH したうえで**（プロジェクト・ゾーンは環境に合わせる）:

```bash
# oauth-server（Google OAuth・/api/meet プロキシ）
sudo docker logs meet-oauth-server-1 --tail=100 -f

# Slack ボット（Socket Mode・メッセージ受信）
sudo docker logs meet-slack-bot-1 --tail=100 -f

# まとめて
cd ~/meet && sudo docker compose logs -f oauth-server slack-bot
```

Slack からテストメッセージを送ったあと、`slack-bot` 側に `Slackイベント受信` や `message` 相当のログが出るか確認してください。

---

## 5. よくある切り分け

| 現象 | 確認 |
|------|------|
| ボットが反応しない | ローカルで `slack_bot` がまだ動いていないか。Socket Mode は**一つの接続**が有効なことが多い。 |
| OAuth リンクが古い ngrok | `.env` の `OAUTH_PUBLIC_BASE_URL` と `credentials.json`、Google Console のリダイレクト URI。 |
| `/api/meet` が 503 | `ios-shortcut-api` と `oauth-server` の両方が起動しているか: `sudo docker compose ps` |
