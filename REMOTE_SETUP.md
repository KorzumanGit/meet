# 他の Mac / iPhone から Google 連携する（OAuth を HTTPS で公開）

Slack のリンクは `OAUTH_PUBLIC_BASE_URL` で作られます。`http://127.0.0.1:8888` のままだと、**ブラウザを開いている端末自身**にしかサーバがありません。別の PC や iPhone から開くには、**ボット用 PC 上で動いている `oauth_server.py` をインターネット経由で HTTPS 公開**する必要があります。

## 自動スクリプト（推奨）

環境変数の一覧は `.env.example` を参照してください。

### A. ngrok（安定しやすい・要無料アカウント）

プロジェクト直下で:

```bash
./remote_oauth.sh
```

**まとめて起動**（`oauth_server` + `slack_bot` のあと ngrok まで続けて実行）:

```bash
./start_stack.sh
```

`oauth_server` を起動し、ngrok で 8888 を HTTPS 公開し、**`.env` に書く `OAUTH_PUBLIC_BASE_URL` と Google に登録するリダイレクト URI** を表示します。

- **予約ドメイン**（ダッシュボードの **Domains** で発行した `*.ngrok-free.dev` など）がある場合は、`.env` に **`NGROK_DOMAIN`** と **`OAUTH_PUBLIC_BASE_URL`** の両方を書くと、`remote_oauth.sh` が `ngrok http 8888 --domain=...` で起動し、**URL が固定**になります（`.env.example` 参照）。
- 予約ドメインがない場合は従来どおりランダム URL のトンネルになります。

**初回のみ** [ngrok ダッシュボード](https://dashboard.ngrok.com/get-started/your-authtoken) でトークンを取得し、次を実行してください:

```bash
ngrok config add-authtoken <あなたのトークン>
```

### B. Cloudflare Quick Tunnel（authtoken 不要・実験向け）

[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) を入れたうえで:

```bash
./remote_oauth_cloudflared.sh
```

`*.trycloudflare.com` の HTTPS URL が表示されます。**無料の実験用トンネル**のため URL が変わりやすく、本番向けではありません。ngrok の設定がまだのときの代替として使えます。

## 固定 URL にしたい（運用・チーム向け）

**新規メンバーが初めて OAuth リンクを踏むたびに `.env` と Google を直すのを避ける**には、**ホスト名が変わらない HTTPS URL** を 1 本決めておきます。以降はトンネルやサーバを再起動しても、**同じ `OAUTH_PUBLIC_BASE_URL`** のまま運用できます（初回連携のたびに編集しない）。

### 1. ngrok の予約ドメイン（要プラン）

[ngrok の Reserved / Static domain](https://ngrok.com/docs/guides/other/reserved-domains/) が使えるプランで、ダッシュボードの **Domains** に例として `your-name.ngrok-free.dev` を確保する。

- `.env`: `NGROK_DOMAIN=your-name.ngrok-free.dev` と `OAUTH_PUBLIC_BASE_URL=https://your-name.ngrok-free.dev`（末尾スラッシュなし）
- トンネル起動: `./remote_oauth.sh`（`--domain` が自動で付く）
- Google Cloud Console: 承認済みリダイレクト URI に `https://your-name.ngrok-free.dev/oauth2callback` を **一度**追加

### 2. 自分のドメイン + Cloudflare Tunnel（名前付き）

ドメインを [Cloudflare](https://dash.cloudflare.com/) に置き、[名前付きトンネル（Named tunnel）](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/) で例: `oauth.example.com` の HTTPS をローカルの `http://127.0.0.1:8888` に向ける。Quick Tunnel（`trycloudflare.com`）とは別で、**固定ホスト名**が取れる。

- `.env`: `OAUTH_PUBLIC_BASE_URL=https://oauth.example.com`
- Google: `https://oauth.example.com/oauth2callback` を登録

### 3. VPS やマネージド PaaS に `oauth_server` だけ載せる

小さな VPS や [Cloud Run](https://cloud.google.com/run) などに Flask の `oauth_server.py` を常時公開し、`https://oauth.example.com` のように **固定のサービス URL** にする。Slack ボットは今まで通り自宅 PC でもよい。

---

上のいずれかにすると、**未連携メンバーが増えても「リンクのベース URL を毎回変える」作業は基本的に不要**になります（Google のテストユーザー追加など、Google 側の設定は別途）。

## 手動: ngrok（例）

1. [ngrok](https://ngrok.com/) をインストールし、アカウントを作成。
2. 上記の `ngrok config add-authtoken` を実行。
3. **OAuth サーバを動かしたまま**、別ターミナルで:

   ```bash
   ngrok http 8888
   ```

4. 表示された **HTTPS の URL**（例: `https://xxxx.ngrok-free.app`）をコピーする。
5. プロジェクトの `.env` を編集:

   ```env
   OAUTH_PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
   ```

   （末尾にスラッシュは付けない）

6. **Google Cloud Console** → API とサービス → 認証情報 → 該当 OAuth クライアント →  
   **承認済みのリダイレクト URI** に次を **追加**（既存の localhost は残してよい）:

   ```
   https://xxxx.ngrok-free.app/oauth2callback
   ```

7. `oauth_server.py` と `slack_bot.py` を **再起動**（環境変数を読み直すため）。
8. Slack で再度ボットにメッセージを送り、**新しい連携 URL**（ngrok 始まり）を開く。

## 注意

- **ngrok 無料枠や Cloudflare Quick Tunnel では URL が変わることがある**。変わったら `.env` と Google のリダイレクト URI を **両方**更新する。
- Google の OAuth 同意画面が **テスト** の場合、**テストユーザー**に連携する Google アカウントを追加する必要がある。
- **本番**では、固定ドメインの VPS や Cloud Run に `oauth_server.py` を載せる方法もある。

## 動作の整理

| コンポーネント | どこで動くか |
|----------------|--------------|
| `slack_bot.py` | 常に起動している 1 台のマシン（Socket Mode）でよい |
| `oauth_server.py` | 同上（ngrok / cloudflared はこのマシンの 8888 にトンネル） |
| ユーザー | どの端末のブラウザからでも、**公開 URL** なら Google 連携可能 |
