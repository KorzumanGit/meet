# humbull.co：権威 NS の不一致を解消する（司令塔メモ）

## 事実確認（再現コマンド）

```bash
dig NS humbull.co +short
# → ns-cloud-c1 … c4.googledomains.com（いまインターネットが信じている権威）

gcloud dns managed-zones describe humbull-co --project=secretary-492601 --format='value(nameServers)'
# → ns-cloud-e1 … e4（secretary-492601 の Cloud DNS ゾーン humbull-co が出す NS）
```

**問題:** レジストラが **c\*** を向けている限り、**e\*** ゾーンに入れた `meet` の A はパブリックに出ない。

---

## 解決策 A：カスタムレコードだけ足す（NS は触らない・推奨で始めやすい）

**向き:** いまの権威（**c\***）の管理画面＝**実際に DNS を編集しているプロバイダ**（多くの場合 **Squarespace Domains** または **Google Domains → Squarespace 移行後の画面**）。

1. ブラウザで Squarespace にログイン（ドメイン購入・接続に使っているアカウント）。
2. **ホーム → 設定（Settings）→ Domains**（または **Website → Domains**）。
3. **humbull.co** を選択 → **DNS** / **DNS 設定** / **Manage DNS** など。
4. **カスタムレコード**で追加:
   - **Host:** `meet`
   - **Type:** `A`
   - **Data / Points to:** `34.84.113.149`
   - **TTL:** 300（あれば）
5. 保存後、反映待ち:

```bash
dig +short meet.humbull.co A @8.8.8.8
# 34.84.113.149 になれば OK
```

**注意:** 本番の `www`（Squarespace サイト）や **MX** 等が既にある場合、**NS だけ差し替えない**ほうが安全。まずは **A 1 行追加**が最小リスク。

---

## 解決策 B：レジストラで NS を **e1〜e4** に切り替える（Cloud DNS に全面委任）

**向き:** `secretary-492601` のゾーン **humbull-co** を**唯一の権威**にしたい場合。

### レジストラで設定する NS（この 4 本をそのまま）

```text
ns-cloud-e1.googledomains.com
ns-cloud-e2.googledomains.com
ns-cloud-e3.googledomains.com
ns-cloud-e4.googledomains.com
```

（末尾の `.` は UI によっては不要）

### 手順（概念）

1. Squarespace / ドメイン管理画面で **Nameservers** を **Custom** に変更。
2. 上記 4 つを登録して保存。

### 必須の注意（落とし穴）

- NS を **c\*** から **e\*** に変えると、**古いゾーンにだけあったレコードは効かなくなる**。
- **先に** Cloud DNS ゾーン `humbull-co` に、少なくとも次を再現すること:
  - ルート `humbull.co` の A（例: Squarespace 用の IP）
  - `www` の CNAME 等
  - **MX**（Google Workspace 等）
  - 既存の **TXT**（SPF 等）
- 移行は **dig @ns-cloud-c1** で現在値を全部メモ → **gcloud dns record-sets create** で e ゾーンへ複製してから NS 切替が安全。

---

## 解決策 C：GCP 上で「c\* ゾーン」がどのプロジェクトか特定できた場合

そのプロジェクトの Cloud DNS で `meet.humbull.co.` の A を追加すれば、**NS を変えず**に済む。  
（司令塔の gcloud では該当ゾーンを列挙できなかったため、組織の別アカウント／別課金で管理されている可能性あり。）

---

## 反映後の完結（Phase 4 / 5）

### Phase 4（VM で SSL）

`dig +short meet.humbull.co A @8.8.8.8` が `34.84.113.149` を返した**後**:

```bash
gcloud compute ssh meet-vm --zone=asia-northeast1-a --project=secretary-492601 --command='
sudo certbot --nginx -d meet.humbull.co --non-interactive --agree-tos -m daisuke.k@humbull.co --redirect
'
curl -sS -o /dev/null -w "%{http_code}\n" https://meet.humbull.co/health
```

### Phase 5（OAuth）

Google Cloud Console → **API とサービス** → **認証情報** → 該当 OAuth クライアント → **承認済みのリダイレクト URI** に:

`https://meet.humbull.co/oauth2callback`

（ブラウザは `deploy/scripts/browser-temp-profile.sh` の一時プロフィール推奨。）

---

## スクリーンショットについて

Cursor は画面キャプチャを生成できない。**メニュー名はプロダクト更新で変わる**ため、上記のキーワード（Domains / DNS / Custom records / Nameservers）で Squarespace ヘルプを検索すると最新 UI に合わせやすい。
