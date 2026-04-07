# Cline 向け実行指示書：DNS（Squarespace）→ HTTPS（Certbot）→ OAuth

**前提（司令塔・Cursor の調査結果）**

- `meet.humbull.co` をパブリックに引きたい。**VM の固定 IP は `34.84.113.149`**（GCP `meet-vm`）。
- `dig humbull.co NS` および権威サーバ上の確認により、**現在の権威ネームサーバーは `ns-cloud-c1`〜`ns-cloud-c4`（Google Domains / Cloud DNS 系）**である一方、**`www.humbull.co` 等は Squarespace（`ext-sq.squarespace.com`）向け**の構成が存在する。
- **GCP `secretary-492601` の Cloud DNS に `humbull-co` ゾーン（NS は `ns-cloud-e1`〜`e4`）を作成済み**だが、**レジストラ側の NS が `e*` に切り替わっていないため、このゾーンはまだインターネットの権威として使われていない**可能性が高い。
- **実際に `meet` の A レコードを「今の権威が向いている DNS 管理画面」に追加する必要がある。** 司令塔の判断として、**ドメインの DNS が Squarespace 経由で管理されている場合は、Squarespace のカスタムレコードで `meet` を追加する**。

**絶対指針**

- **指針第2条（SingletonLock 回避）:** ブラウザ操作の前に必ず  
  `bash deploy/scripts/browser-temp-profile.sh`  
  を実行し、表示された `CLINE_CHROME_USER_DATA_DIR` で Chrome を起動すること（本番 Chrome プロフィールと共有しない）。
- **指針第4条（自己修復）:** エラー時はログイン・セレクタ変更・待機時間を調整して再試行し、試した内容と結果だけを報告する。
- **Slack の Web ログインは禁止**（変更なし）。

---

## タスク 1：Squarespace で DNS A レコードを追加

1. 作業ディレクトリはリポジトリルート（`meet/`）。
2. `bash deploy/scripts/browser-temp-profile.sh` を実行し、一時プロフィールでブラウザを起動。
3. Squarespace にログインし、**該当ドメイン `humbull.co` の DNS / カスタムレコード**管理へ進む（UI は Squarespace のバージョンにより異なる。ドメイン接続・Advanced DNS 等を探す）。
4. 次を追加または更新する（既存の `meet` があれば IP のみ更新）:
   - **Host / Name:** `meet`（または `meet.humbull.co` 形式。Squarespace の表記に合わせる）
   - **Type:** A
   - **Value / Points to:** `34.84.113.149`
   - **TTL:** 300 または UI 上で選べる最短
5. 保存後、**パブリック DNS の反映を待つ**:
   - `dig +short meet.humbull.co A @8.8.8.8` が **`34.84.113.149`** を返すまでループ（例: 10〜30 秒間隔、最大 30 分）。

**注意:** もし Squarespace 上に `meet` を置けない・ドメインが別管理の場合は、**実際に `ns-cloud-c1`〜`c4` の権威を持つ管理画面**（Google Domains の DNS、または該当 Cloud DNS プロジェクト）に切り替えて同じ A レコードを追加する。目標は「**パブリックが `meet` → 34.84.113.149 を返す**」こと。

---

## タスク 2：VM で Certbot（HTTPS 化）

**前提:** タスク 1 で `dig @8.8.8.8 meet.humbull.co` が `34.84.113.149` になった後のみ実行。

```bash
export GCP_PROJECT_ID="secretary-492601"
export GCP_ZONE="asia-northeast1-a"
export VM_NAME="meet-vm"

gcloud compute ssh "$VM_NAME" --zone="$GCP_ZONE" --project="$GCP_PROJECT_ID" --command='
sudo certbot --nginx -d meet.humbull.co --non-interactive --agree-tos -m daisuke.k@humbull.co --redirect
sudo nginx -t && sudo systemctl reload nginx
curl -sS -o /dev/null -w "%{http_code}" https://meet.humbull.co/health
'
```

（メールはプロジェクトの連絡先に合わせてよい。nginx は前段で `80 → 127.0.0.1:8888` 済み想定。）

---

## タスク 3：Google Cloud Console で OAuth リダイレクト URI

1. 再び **一時プロフィール**でブラウザを起動（タスク 1 と同じ手順）。
2. **Google Cloud Console** → **API とサービス** → **認証情報** → 該当 **OAuth 2.0 クライアント ID**（`credentials.json` と一致するクライアント）。
3. **承認済みのリダイレクト URI** に次を追加:
   - `https://meet.humbull.co/oauth2callback`
4. 保存。

---

## 完了報告（Cline が最後に出す情報）

- `dig +short meet.humbull.co A @8.8.8.8` の結果
- `curl -sS -o /dev/null -w "%{http_code}\n" https://meet.humbull.co/health` の HTTP ステータス
- Certbot が成功したか（要約）
- OAuth URI を保存したか（はい／いいえ）

---

## 参照ファイル（リポジトリ内）

- `deploy/scripts/browser-temp-profile.sh`
- `deploy/CLINE_FULL_RUNBOOK.md`（VM・変数・nginx）
- `deploy/CLINE_START_HERE.txt`
