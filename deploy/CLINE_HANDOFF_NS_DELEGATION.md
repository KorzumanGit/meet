# Cline 向け：ネームサーバー委任（c\* → e\*）と Phase 4/5 完結

## 司令塔が完了した作業（gcloud）

**プロジェクト:** `secretary-492601`  
**ゾーン:** `humbull-co`（`humbull.co.`）

旧権威（`ns-cloud-c1`〜`c4`）から **dig で取得したレコード**を Cloud DNS に複製済み：

| 名前 | 種別 | 内容 |
|------|------|------|
| `humbull.co.` | A | `198.185.159.144`（Squarespace サイト用 apex） |
| `humbull.co.` | MX | `1 smtp.google.com.` |
| `humbull.co.` | TXT | SPF（Google Workspace） |
| `www.humbull.co.` | CNAME | `ext-sq.squarespace.com.` |
| `meet.humbull.co.` | A | `34.84.113.149`（GCP VM） |
| `google._domainkey.humbull.co.` | TXT | DKIM（旧ゾーンと同一内容・255 文字分割） |

**確認コマンド:**

```bash
gcloud dns record-sets list --zone=humbull-co --project=secretary-492601
```

---

## レジストラで設定するカスタム NS（この 4 本をそのまま登録）

**Cloud DNS ゾーン `humbull-co` が権威になるよう、ドメインのネームサーバーを次に切り替える：**

```text
ns-cloud-e1.googledomains.com
ns-cloud-e2.googledomains.com
ns-cloud-e3.googledomains.com
ns-cloud-e4.googledomains.com
```

（UI によっては末尾の `.` なしで入力）

---

## Google Workspace 管理コンソールでの操作（人間または Cline ブラウザ）

1. **一時プロフィール:** `bash deploy/scripts/browser-temp-profile.sh` を実行し、出力された `--user-data-dir` で Chrome を起動（指針第2条）。
2. **Google 管理コンソール**に管理者でログイン: https://admin.google.com  
3. **メニュー:** **アカウント** → **アカウント** → **ドメイン** → **ドメインの管理**（表記は英語 UI では **Account** → **Domains** → **Manage domains**）。
4. **humbull.co** を選択 → **詳細を表示** / **Manage domain**。
5. **DNS / ネームサーバー**関連のセクションを開く（例: 「DNS 設定」「ネームサーバー」「名前解決の設定」）。
6. **ネームサーバー**を **カスタム** に変更し、上記 **4 本**を登録して保存。

> 補足: ドメインが **Squarespace 登録のみ**で Workspace 管理に出てこない場合は、**Squarespace Domains** 側の「Custom nameservers」で同じ 4 本を設定する。  
> 参考: Google の名前サーバー変更の一般手順: https://support.google.com/a/answer/3290430

---

## NS 切替後の自動検証（Cline が実行）

```bash
# パブリックに e* が見えるまで数分〜48時間かかる場合あり
until dig +short humbull.co NS @8.8.8.8 | grep -q 'ns-cloud-e'; do sleep 30; done
dig +short meet.humbull.co A @8.8.8.8
# 期待: 34.84.113.149
```

---

## Phase 4（Certbot）— `meet` が引けた後のみ

```bash
gcloud compute ssh meet-vm --zone=asia-northeast1-a --project=secretary-492601 --command='
sudo certbot --nginx -d meet.humbull.co --non-interactive --agree-tos -m daisuke.k@humbull.co --redirect
'
curl -sS -o /dev/null -w "%{http_code}\n" https://meet.humbull.co/health
```

---

## Phase 5（OAuth）

Google Cloud Console → **API とサービス** → **認証情報** → 該当 OAuth クライアント → **承認済みのリダイレクト URI** に:

`https://meet.humbull.co/oauth2callback`

（ブラウザは一時プロフィールを使用）

---

## 注意（既存レコードの欠落リスク）

- 旧ゾーンに **c1 から取得できなかった** レコード（将来追加されたサブドメイン等）は **手動で Cloud DNS に足す**必要がある。
- 切替後にメール到達性を確認する（MX / DKIM / SPF は本ゾーンにコピー済み）。
