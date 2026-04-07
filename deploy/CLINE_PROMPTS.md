# Cline 向けプロンプト集（GCP デプロイ 1〜7）

**→ 実行は [`CLINE_FULL_RUNBOOK.md`](./CLINE_FULL_RUNBOOK.md) と [`CLINE_FINAL_PROMPT.txt`](./CLINE_FINAL_PROMPT.txt) を正とする（本ファイルは概要用）。**

**禁止事項:** Slack の Web に**ログイン**する操作は行わない（トークンは既存のものを `.env` に貼る前提）。

**前提:** Google Cloud のプロジェクトが既にある、課金が有効、あなた（人間）がブラウザで GCP / Google にログインできる。

---

## フェーズ 1 — VM + ファイアウォール + 固定 IP

次を **同一プロジェクト・同一リージョン**で実行する手順を、ターミナル用コマンド付きで実行し、結果（VM 名、外部 IP、ゾーン）を要約して報告してください。

```
目的:
- Compute Engine で Ubuntu 22.04 LTS の VM を 1 台作成する
- マシンタイプは e2-small 程度でよい
- 外部 IP は「固定（静的）」を付与する
- VPC ファイアウォールで次を許可する: tcp/22 (SSH), tcp/80 (HTTP), tcp/443 (HTTPS)
- 作成後、gcloud で VM の外部 IP を表示する

制約:
- Slack のブラウザログインは行わない
- 出力は VM 名、ゾーン、外部 IP、使ったファイアウォールルール名だけ簡潔に
```

---

## フェーズ 2 — ドメイン（A レコード）

人間がドメインを持っている前提で、次のどちらかで **A レコードをフェーズ 1 の外部 IP に向ける**手順を書く。

```
目的:
- 例: meet.example.com を VM の固定 IP に向ける
- Cloud DNS を使う場合と、お名前.com 等のレジストラで A レコードだけ貼る場合の両方を短く

制約:
- Slack 操作はしない
```

---

## フェーズ 3 — VM 上で Docker + アプリデプロイ

SSH で VM に入ったあと実行するコマンド列を、**コピペ可能なブロック**で出力する。

```
目的:
- Docker Engine と Docker Compose プラグインをインストール（Ubuntu 公式手順に準拠）
- git でリポジトリを clone（URL はプレースホルダでよい）
- meet ディレクトリで:
  - .env と ios-shortcut-api/.env は「ホームから scp でコピー済み」と仮定し、存在チェックのみ
  - credentials.json が meet/ にあること
  - data/google_tokens/ が必要なら配置済み
- `docker compose build` と `docker compose up -d`
- `curl -s http://127.0.0.1:8888/health` が ok になることを確認

環境変数の注意:
- meet/.env に OAUTH_PUBLIC_BASE_URL=https://（フェーズ2のドメイン）を設定済みであること
- IOS_SHORTCUT_API_BASE は docker-compose の environment で上書きされる想定（手動で書かなくてよい）

制約:
- Slack ログインは禁止
- 秘密情報をチャットに書き戻さない（マスクする）
```

---

## フェーズ 4 — nginx + Let’s Encrypt

```
目的:
- Ubuntu に nginx をインストール
- deploy/nginx-meet.conf.example を参考に、server_name と SSL パスを実ドメインに合わせた設定を /etc/nginx/sites-available に作成
- certbot --nginx で HTTPS 証明書を取得
- nginx を reload
- curl -s https://実ドメイン/health が ok になることを確認

制約:
- Slack の操作は一切しない
```

---

## フェーズ 5 — Google OAuth（Calendar 用クライアント）

**これは Slack ではなく、Google Cloud Console の OAuth 設定です。**

```
目的:
- Google Cloud Console → 対象プロジェクト → APIs & Services → Credentials
- OAuth 2.0 クライアント（デスクトップまたはウェブ）の「承認済みのリダイレクト URI」に次を追加:
  https://（フェーズ2のドメイン）/oauth2callback
- 保存

注意:
- ブラウザで Google にログインするのは人間が行う。Cline は手順とスクリーンショット位置だけ案内する。
- Slack のログイン・Slack の Web 設定は行わない。
```

---

## フェーズ 6 — iOS ショートカット

```
目的:
- ショートカットの HTTP リクエストの URL を
  https://（ドメイン）/api/meet
 に変更する手順を箇条書きで書く（iPhone 側の操作）
- API_KEY を使っている場合は、ヘッダ x-api-key の説明を一言

制約:
- Slack ログイン禁止
```

---

## フェーズ 7 — 動作確認

```
目的:
- curl https://ドメイン/health
- Slack: ボットが既に起動していれば、チャンネルでテストメッセージを送ると反応するか（※Slack にブラウザログインはしない。モバイルアプリから送る等）
- ショートカットから 1 件テスト

制約:
- Slack のブラウザログインは行わない
```

---

## トークン類（人間がローカルで行う・ログインは最小限）

- **Slack:** `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` は **既存の値**を VM の `meet/.env` にコピーする（Slack Web にログインしない）。
- **Google:** OAuth リダイレクト追加のため **Google Cloud Console** に入る必要がある場合のみ、人間がログインする。
