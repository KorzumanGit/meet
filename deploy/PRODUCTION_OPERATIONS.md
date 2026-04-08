# 本番運用ルール（GCP VM / `https://meet.humbull.co`）

以降の開発・デプロイ作業は **本番がこの環境** であることを前提とする。

## 1. 環境の同期

- ローカルで変更したコードは、**VM の `~/meet` に反映する**まで作業完了としない。
- 反映手段の例:
  - **`git push` 後、VM で `git pull`**（推奨・履歴が残る）
  - **`gcloud compute scp`** で個別ファイルを上書き（緊急・小差分）

## 2. 設定の保護（破壊禁止）

次を **意図的に上書き・削除・差し替えしない**（必要な場合は事前に明示し、バックアップを取る）:

- VM 上の **`~/meet/.env`**
- **`~/meet/credentials.json`**
- **`/etc/nginx/`** 配下の本番サイト設定・**Let’s Encrypt** 取得済み証明書まわり
- その他、本番のみの秘密・パス

## 3. デプロイ手順（コード変更後）

VM に SSH したうえで `~/meet` で実行:

```bash
cd ~/meet
sudo docker compose up -d --build
# または変更サービスのみ
sudo docker compose up -d --build oauth-server
sudo docker compose restart oauth-server
```

変更内容に応じて **ビルドが不要なら `restart` のみ**でよい。

## 4. ログ確認（必須）

反映後、エラーがないか確認:

```bash
cd ~/meet
sudo docker compose logs --tail=80
# 継続監視
sudo docker compose logs -f
```

対象は少なくとも **`oauth-server`**・**`slack-bot`**・**`ios-shortcut-api`** のいずれかが関係する場合は該当サービスを指定。

## 参照

- 全体概要: [`DEPLOY_GCP.md`](./DEPLOY_GCP.md)
