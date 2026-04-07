# GCP 上で常時稼働させる（Compute Engine + Docker）

Mac をスリープさせても、外出先の Wi‑Fi からショートカットや Slack が使えるようにするには、**このリポジトリを Linux（VM）上で動かし、HTTPS のドメインで公開**します。ngrok は不要です。

- **Cline に任せる用のプロンプト集:** [`deploy/CLINE_PROMPTS.md`](./CLINE_PROMPTS.md)（Slack ブラウザログインは含めない）
- **高解像度・一括実行ブック:** [`deploy/CLINE_FULL_RUNBOOK.md`](./CLINE_FULL_RUNBOOK.md)
- **Cline 引き継ぎ（Squarespace DNS → Certbot → OAuth）:** [`deploy/CLINE_HANDOFF_SQUARESPACE_DNS.md`](./CLINE_HANDOFF_SQUARESPACE_DNS.md)
- **手足への最終指令書:** [`deploy/CLINE_START_HERE.txt`](./CLINE_START_HERE.txt)（人間の一言: `@deploy/CLINE_START_HERE.txt 実行開始`）→ [`deploy/CLINE_FINAL_PROMPT.txt`](./CLINE_FINAL_PROMPT.txt)
- **リダイレクト:** リポジトリ直下 [`CLINE_START_HERE.txt`](../CLINE_START_HERE.txt) は `deploy/CLINE_START_HERE.txt` へ誘導のみ
- **信号（ターミナル）:** `bash deploy/scripts/cline-handoff-signal.sh`（`.cline_handoff_requested` を更新）
- **Cline に貼る最終プロンプト（1 ブロック）:** [`deploy/CLINE_FINAL_PROMPT.txt`](./CLINE_FINAL_PROMPT.txt)
- **一時ブラウザプロフィール（SingletonLock 回避）:** [`deploy/scripts/browser-temp-profile.sh`](./scripts/browser-temp-profile.sh)
- **実装計画:** [`deploy/IMPLEMENTATION_PLAN_GCP.md`](./IMPLEMENTATION_PLAN_GCP.md)

## 全体像

1. **Compute Engine VM**（例: `e2-small`、Ubuntu 22.04）を 1 台用意する。
2. VM 上で **`docker compose`** により次を起動する。
   - `ios-shortcut-api`（内部ポート 3847）
   - `oauth-server`（**127.0.0.1:8888** のみ公開。`IOS_SHORTCUT_API_BASE` で Node に中継）
   - `slack-bot`（Slack Socket Mode）
3. **nginx + Let’s Encrypt** で **443 → 127.0.0.1:8888** をリバースプロキシする。
4. **ドメイン**の A レコードを VM の**固定外部 IP**に向ける。
5. **Google Cloud Console（OAuth）**の「承認済みのリダイレクト URI」に  
   `https://あなたのドメイン/oauth2callback` を追加する。
6. **`meet/.env`** の `OAUTH_PUBLIC_BASE_URL=https://あなたのドメイン` にする（末尾スラッシュなし）。

ショートカットの URL は **`https://あなたのドメイン/api/meet`**（`oauth_server` が 3847 に転送）。

## 手順（概要）

### 1. GCP で VM を作る

- プロジェクトを作成し、**Compute Engine API** を有効化。
- **VM インスタンス**を作成: 外部 IP は**固定**推奨。
- ファイアウォールで **tcp:22（SSH）** と **tcp:443**（および certbot 初回用に **tcp:80**）を許可。

### 2. VM に Docker を入れる

公式手順に従い **Docker Engine** と **Docker Compose プラグイン**をインストールする。

### 3. リポジトリと秘密情報を配置する

```bash
git clone <このリポジトリ> meet
cd meet
cp .env.example .env
cp ios-shortcut-api/.env.example ios-shortcut-api/.env
# .env を編集（Slack / OpenAI / OAUTH_PUBLIC_BASE_URL など）
# credentials.json を meet/ に配置
# data/google_tokens/ に各ユーザーの JSON を配置（必要に応じて）
```

**Docker 用の環境変数の例**

- `meet/.env`  
  - `OAUTH_PUBLIC_BASE_URL=https://あなたのドメイン`  
  - `OAUTH_SERVER_HOST` は **compose で `0.0.0.0` を指定済み**（Flask がコンテナ外から叩けるようにするため）。
- `IOS_SHORTCUT_API_BASE` は **compose で `http://ios-shortcut-api:3847` を指定済み**（上書き不要）。
- `ios-shortcut-api/.env`  
  - `GOOGLE_TOKEN_FILE` は **`../data/google_tokens/Uxxxx.json`** のままでよい（コンテナ内で `/usr/src/data` にマウントされる）。

### 4. Docker Compose で起動

```bash
cd meet
docker compose build
docker compose up -d
docker compose ps
curl -s http://127.0.0.1:8888/health
```

### 5. nginx と HTTPS

- `deploy/nginx-meet.conf.example` を参考にサイト設定を作成する。
- **certbot** で証明書を取得し、`nginx -t` のあと `systemctl reload nginx`。

### 6. 動作確認

- ブラウザ: `https://あなたのドメイン/health` → `ok`
- ショートカット: `POST https://あなたのドメイン/api/meet`（必要なら `x-api-key`）

## 秘密情報の扱い

- **本番**では `.env` をそのまま VM に置かず、**Secret Manager** や **systemd EnvironmentFile** で注入する運用を推奨。
- **credentials.json** と **google_tokens** のパーミッションを厳しめにする。

## トラブルシュート

| 現象 | 確認 |
|------|------|
| OAuth がループする | `OAUTH_PUBLIC_BASE_URL` と Google のリダイレクト URI が完全一致か（http/https・末尾スラッシュ） |
| 503 on `/api/meet` | `docker compose logs ios-shortcut-api`、3847 のヘルス |
| Slack が反応しない | `slack_bot` コンテナのログ、`SLACK_APP_TOKEN` / `SLACK_BOT_TOKEN` |

## 参考

- ローカル・ngrok 向けの説明は `REMOTE_SETUP.md`
- コンテナ定義はリポジトリ直下の `docker-compose.yml`
