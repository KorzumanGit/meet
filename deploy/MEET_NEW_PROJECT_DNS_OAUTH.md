# 新プロジェクト（例: `260403-call-meeting`）と OAuth 移行チェックリスト

## 前提

- **VM（meet-vm）** は従来どおり **`secretary-492601`** 上で動かす想定（IP `34.84.113.149`）。
- **Cloud DNS** を **`260403-call-meeting` の `humbull-co-main`** に置いた場合、**レジストラの NS がそのゾーンの NS（例: `ns-cloud-d1`〜`d4`）になっていること**が、パブリックに `meet` を出す条件。

## 1. DNS 反映の確認（ローカル）

```bash
dig NS humbull.co +short @8.8.8.8
dig +short meet.humbull.co A @8.8.8.8
# 期待: NS が d 系（または新ゾーンの NS）、A が 34.84.113.149
```

**A が空のまま**のときは、NS 切替の伝播待ち（TTL）か、**レジストラ側の NS がまだ新ゾーンを指していない**可能性がある。

## 2. HTTPS（Certbot）— DNS が通った後のみ VM で実行

```bash
gcloud compute ssh meet-vm --zone=asia-northeast1-a --project=secretary-492601 --command='
sudo certbot --nginx -d meet.humbull.co --non-interactive --agree-tos -m daisuke.k@humbull.co --redirect
curl -sS -o /dev/null -w "%{http_code}\n" https://meet.humbull.co/health
'
```

（nginx は既に `80 → 127.0.0.1:8888` 前提。）

## 3. OAuth を「新プロジェクト」のクライアントに合わせる

1. **Google Cloud Console** → 新プロジェクト **`260403-call-meeting`** を選択。
2. **API とサービス** → **認証情報** → **OAuth 2.0 クライアント ID** を作成（または既存を選択）。
3. **承認済みのリダイレクト URI** に追加:  
   `https://meet.humbull.co/oauth2callback`
4. **JSON をダウンロード**し、VM / リポジトリの **`credentials.json`** として配置（既存の `oauth_server` の `credentials.json` と置き換え）。
5. コンテナを再読み込み:

```bash
# VM 上
cd ~/meet && sudo docker compose up -d --force-recreate oauth-server
```

**注意:** クライアント ID / シークレットが変わると、**Google 側で Calendar API 等が有効**か、**OAuth 同意画面**が必要なスコープを含むかを再確認すること。

## 4. 権限のない gcloud アカウント

このリポジトリの `gcloud` が **`260403-call-meeting` を参照できない**場合は、**IAM で閲覧権限を付与**するか、**新プロジェクトの OAuth JSON を手元で `scp` する**運用にする。
