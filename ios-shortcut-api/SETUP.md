# iPhone（Siri / ショートカット）→ Mac API → Meet / カレンダー / Slack

**「Mac の中で動く司令塔（API）」を iPhone から呼び出す**ための最短ルートです。

---

## 確実に daisuke.k@humbull.co のカレンダーに入れる（ショートカット経由）

ショートカットは **`ios-shortcut-api` の `.env` に書いた Google トークンだけ**を使います（Slack の送信者とは無関係）。次の順で進めてください。

### A. トークンを「daisuke の Google」だけにする

1. **Mac** で `./start_services.sh`（または `oauth_server` を 8888 で起動）と **`ios-shortcut-api`（3847）** が動いていることを確認する。
2. **ブラウザ**で次を開く（`<daisukeのSlackユーザーID>` は Slack プロフィールの `U` で始まる ID）:
   - `http://127.0.0.1:3847/auth/google?slack_user_id=<daisukeのSlackユーザーID>`
3. Google の画面では **必ず `daisuke.k@humbull.co` を選んで**許可する（他アカウント不可）。
4. 完了後、`meet/data/google_tokens/<同じU>.json` ができる。
5. **`ios-shortcut-api/.env`** を次のようにする（**`GOOGLE_REFRESH_TOKEN` は空のままか削除**し、**`GOOGLE_TOKEN_FILE` だけ**にするのがおすすめ）:
   - `GOOGLE_CALENDAR_OWNER_EMAIL=daisuke.k@humbull.co`
   - `GOOGLE_TOKEN_FILE=../data/google_tokens/<同じU>.json`
6. `npm run build` のあと **`start_services.sh` で再起動**。

### B. トークンが daisuke と一致しているか確認する

Mac のターミナルで:

```bash
curl -s http://127.0.0.1:3847/api/google-calendar-status
```

`ownerMatchesExpected` が **`true`**、`primaryCalendarId` が **`daisuke.k@humbull.co`** なら、このあとショートカットから送った予定も **同じカレンダー**に入ります。

`.env` に `API_KEY` がある場合は:

```bash
curl -s -H "x-api-key: <同じ値>" http://127.0.0.1:3847/api/google-calendar-status
```

iPhone からこの URL を開く場合は **`API_KEY` を設定して `x-api-key` を付ける**か、Mac 上の `curl` で確認してください。

### C. ショートカットを「作り直す」

1. **ショートカット**アプリで、該当ショートカットを**削除**するか、**複製して名前を変えて**中身だけ入れ直す。
2. **URL の内容を取得**だけを使い、次を厳守する:
   - **URL:** `https://<あなたのngrokまたはMacのIP>:3847/api/meet`  
     - ngrok が **8888 向け**のときは **`https://<ngrok>/api/meet`**（`oauth_server` が 3847 に転送する）
     - **パスは必ず `/api/meet`**（`/oauth` やトップ URL ではない）
   - **メソッド:** POST  
   - **ヘッダー:** `Content-Type` = `application/json`（`API_KEY` 使用時は `x-api-key` も）
   - **本文:** JSON、`text` キーに音声入力の結果を渡す

```json
{ "text": "音声入力の結果" }
```

3. 保存し、一度テストする。`503` が返る場合は **A のトークン**がまだ無いか、**再起動**していない。

---

## ステップ 1：Mac で司令塔（API）を動かす

### 1-1. 依存関係とビルド

```bash
cd ios-shortcut-api
npm install
npm run build
```

### 1-2. 環境変数

`.env` に Google OAuth（`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` または `GOOGLE_TOKEN_FILE`）と Slack（`SLACK_BOT_TOKEN` または Webhook、`SLACK_CHANNEL_ID` など）を設定します。  
テンプレートは `.env.example` を参照。

**必要な Google スコープ:** `https://www.googleapis.com/auth/calendar.events`

### 1-3. 起動

```bash
npm start
# 開発時は: npm run dev
```

リポジトリの `meet/` で Slack ボットとまとめて動かす場合は **`cd meet` のうえで `./start_services.sh`** または **`./start_stack.sh`**（ngrok まで）を実行すると、**`oauth_server`（8888）とあわせて `ios-shortcut-api`（3847）も起動**します。

デフォルトで **`http://127.0.0.1:3847`** で待ち受けます。動作確認:

```bash
curl -s http://127.0.0.1:3847/health
curl -s -X POST http://127.0.0.1:3847/api/meet \
  -H "Content-Type: application/json" \
  -d '{"text":"明日15時から30分ミーティング"}'
```

`.env` に `API_KEY` がある場合は、リクエストヘッダに `x-api-key: <同じ値>` を付けます。

---

## ステップ 2：iPhone のショートカットを作る

同じ Wi‑Fi 上で、**Mac のローカル IP** を使います（例: `192.168.3.52`）。  
**システム設定 → ネットワーク** などで Mac の IPv4 を確認してください。

1. **ショートカット**アプリ → **新規ショートカット**
2. アクションを追加:
   - **「テキストを音声入力」**（表示されない場合は **「ディクテーション」** や **「テキストを聞く」** など、音声→テキストになるもの）
3. **「URL の内容を取得」** を追加:
   - **URL:** `http://<MacのIPアドレス>:3847/api/meet`
   - **メソッド:** POST
   - **ヘッダー:**
     - `Content-Type` → `application/json`
     - （`API_KEY` 使用時）`x-api-key` → 値を設定
   - **リクエスト本文:** **JSON** を選び、例として次のようにマッピング:
     - キー `text`、値に **「ショートカット入力」**（直前の音声入力の結果）を接続

JSON の例（ショートカット内の辞書で表現する場合）:

```json
{ "text": "<音声入力の結果が入る>" }
```

---

## ステップ 3：Siri で起動する

1. ショートカットの名前を短く分かりやすくする（例: **「会議の予約」**）
2. ショートカットの **⋯（詳細）→ Siri に追加** でフレーズを登録
3. **「Hey Siri、会議の予約」** などと話し、聞かれたら **「明日15時から打ち合わせ」** のように依頼

### 最終的な流れ

1. iPhone が声をテキストにし、**POST `/api/meet`** で Mac に送る  
2. Mac 上の API が日時を解釈し、**Google Meet** を発行して **カレンダーに登録**  
3. **Slack**（既定チャンネル `C0AR1VBT3ED` など）に「予約しました・URL は…」と投稿  

---

## 外出先（4G/5G）で使う：ngrok

自宅 Wi‑Fi 外から Mac に届かないときは、Mac で API を **HTTPS で公開**します。

```bash
cd ios-shortcut-api
./ngrok_public.sh
```

表示された **`https://xxxx.ngrok-free.app`** を、ショートカットの URL を  
`https://xxxx.ngrok-free.app/api/meet` に差し替えます（**https** のまま POST）。

初回は `ngrok config add-authtoken <トークン>` が必要です。

**ngrok が 8888 のみの場合:** 親ディレクトリの `meet/oauth_server.py` が **`POST /api/meet` を `http://127.0.0.1:3847/api/meet` に転送**します。次の **両方**を起動したうえで、ショートカットの URL は **`https://（8888 用 ngrok）/api/meet`** のままで構いません。

1. `cd ios-shortcut-api && npm start`（3847）
2. `meet/` で `python oauth_server.py`（8888）※ 通常は `start_stack.sh` 等で起動済み

Node だけ止まっていると **503**（接続できません）になります。

---

## トラブルシュート

| 症状 | 確認 |
|------|------|
| **404 Not Found**（英語のエラーページ） | **古い `oauth_server.py`** のとき 8888 に `/api/meet` が無い。`meet/oauth_server.py` を最新にし **OAuth サーバを再起動**。または ngrok を **3847** 向けにする（`./ngrok_public.sh`） |
| **503**（JSON で接続できません） | `ios-shortcut-api` が **3847** で起動しているか（`npm start`） |
| **503**（Google カレンダーが未連携） | `.env` にトークンがない。上記「確実に daisuke…」の A を実施 |
| 予定が **別人（例: kota.n）** のカレンダーに入る | `curl /api/google-calendar-status` で `ownerMatchesExpected` が false。OAuth を **daisuke.k@humbull.co** でやり直し。Slack ボット経由の予定は `meet/.env` の `SCHEDULE_FORCE_CALENDAR_SLACK_USER_ID` も参照 |
| iPhone から繋がらない | 同一 Wi‑Fi か、Mac のファイアウォールで **3847** を許可 |
| 401 | `.env` の `API_KEY` とヘッダ `x-api-key` |
| Slack に来ない | Bot がチャンネルに入っているか、`SLACK_BOT_TOKEN` / Webhook |
