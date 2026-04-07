# Cline 用：GCP デプロイ完全実行ブック（高解像度）

**禁止:** Slack Web へのログイン。トークンは既存値を VM の `.env` に scp。

**ブラウザ（指針第2条）:** 操作前に `bash deploy/scripts/browser-temp-profile.sh` を実行し、出力された `--user-data-dir` を使う（SingletonLock 回避）。

---

## 変数（先頭で一度だけ設定）

```bash
export GCP_PROJECT_ID="secretary-492601"
export GCP_REGION="asia-northeast1"
export GCP_ZONE="asia-northeast1-a"
export VM_NAME="meet-vm"
export STATIC_ADDR_NAME="meet-static-ip"
export FIREWALL_RULE="meet-allow-22-80-443"
export GIT_REPO_URL="https://github.com/humbull/meet.git"   # または SSH
export MEET_DOMAIN="meet.humbull.co"   # フェーズ2で使う FQDN（証明書・OAuth 用）
```

---

## フェーズ 0 — gcloud と API

```bash
gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable compute.googleapis.com --project "$GCP_PROJECT_ID"
# 課金: プロジェクトに課金アカウントが紐付いていること（コンソールで確認。CLI: gcloud beta billing projects describe "$GCP_PROJECT_ID"）
```

---

## フェーズ 1 — 静的 IP + ファイアウォール + VM

```bash
# 1) 静的外部 IP（リージョン）
gcloud compute addresses create "$STATIC_ADDR_NAME" --region="$GCP_REGION" --project "$GCP_PROJECT_ID"
export STATIC_IP=$(gcloud compute addresses describe "$STATIC_ADDR_NAME" --region="$GCP_REGION" --format='get(address)')

# 2) ファイアウォール（タグ meet-server に適用）
gcloud compute firewall-rules create "$FIREWALL_RULE" \
  --project "$GCP_PROJECT_ID" \
  --direction=INGRESS --priority=1000 --network=default \
  --action=ALLOW --rules=tcp:22,tcp:80,tcp:443 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=meet-server

# 3) VM（Ubuntu 22.04、静的 IP を割当）
gcloud compute instances create "$VM_NAME" \
  --project "$GCP_PROJECT_ID" \
  --zone="$GCP_ZONE" \
  --machine-type=e2-small \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=20GB \
  --tags=meet-server \
  --address="$STATIC_ADDR_NAME"

# 4) 確認
gcloud compute instances describe "$VM_NAME" --zone="$GCP_ZONE" --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

**報告項目:** `VM_NAME`, `GCP_ZONE`, `STATIC_IP`, ファイアウォール名。

---

## フェーズ 2 — DNS（人間のレジストラ or Cloud DNS）

- **レジストラ:** タイプ A、ホスト `@` または `meet`、値 `STATIC_IP`、TTL 300。
- **Cloud DNS:** ゾーンに A レコードを追加し、`gcloud dns record-sets list` で確認。

DNS 伝播待ち: `dig +short "$MEET_DOMAIN"` が `STATIC_IP` を返すまで待つ（数分〜数十分）。

---

## フェーズ 3 — VM 内: Docker + アプリ

**ローカルから SSH（初回は鍵登録）:**

```bash
gcloud compute ssh "$VM_NAME" --zone="$GCP_ZONE" --project "$GCP_PROJECT_ID"
```

**VM 上:**

```bash
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# 再ログインするか newgrp docker
```

```bash
git clone "$GIT_REPO_URL" meet
cd meet
# credentials.json / .env / ios-shortcut-api/.env / data/google_tokens は scp で事前投入:
# （ローカルから） gcloud compute scp --zone="$GCP_ZONE" ./credentials.json "$VM_NAME":~/meet/
# （ローカルから） gcloud compute scp --recurse .env "$VM_NAME":~/meet/.env  など

# meet/.env に必須:
#   OAUTH_PUBLIC_BASE_URL=https://$MEET_DOMAIN
# （末尾スラッシュなし）

docker compose build
docker compose up -d
curl -sS http://127.0.0.1:8888/health
curl -sS http://127.0.0.1:3847/health   # 127.0.0.1 はホストの docker ポート公開設定に依存。compose では oauth のみ 8888 がホストにバインド。3847 は内部のみなら、docker exec または oauth 経由で確認。
```

**3847 は compose で expose のみの場合、VM 上では:**

```bash
docker compose exec ios-shortcut-api curl -sf http://127.0.0.1:3847/health
```

---

## フェーズ 4 — nginx + Let’s Encrypt（VM 上）

```bash
sudo apt-get install -y nginx
sudo cp ~/meet/deploy/nginx-meet.conf.example /tmp/meet.conf
# /tmp/meet.conf 内の your-domain.example.com を $MEET_DOMAIN に置換し、証明書パスは certbot 後に合わせる

sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d "$MEET_DOMAIN" --non-interactive --agree-tos -m YOUR_EMAIL --redirect
sudo nginx -t && sudo systemctl reload nginx
curl -sS "https://$MEET_DOMAIN/health"
```

---

## フェーズ 5 — Google OAuth リダイレクト URI

**ブラウザ:** `bash deploy/scripts/browser-temp-profile.sh` の `CLINE_CHROME_USER_DATA_DIR` を使い、Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 クライアント → 承認済みリダイレクト URI に追加:

`https://$MEET_DOMAIN/oauth2callback`

**Slack の操作はしない。**

---

## フェーズ 6 — iOS ショートカット

人間の iPhone: URL を `https://$MEET_DOMAIN/api/meet` に変更。`x-api-key` 使用時はヘッダを維持。

---

## フェーズ 7 — 検証

```bash
curl -sS "https://$MEET_DOMAIN/health"
docker compose -f ~/meet/docker-compose.yml logs --tail=50
```

Slack テストは **モバイルアプリ等**で送信（ブラウザログイン禁止）。

---

## エラー時（指針第4条）

- `gcloud` 認証エラー → `gcloud auth login`（人間）または WIF/SA。
- 443 不通 → ファイアウォール・DNS・nginx・certbot の順に確認。
- 503 on `/api/meet` → `docker compose logs ios-shortcut-api` と `oauth-server`。
