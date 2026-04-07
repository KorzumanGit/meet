# GCP デプロイ：実装計画（承認用）

## 目的

手順 1〜7 を **コード・ドキュメント・Cline 用プロンプト**で再現可能にし、**Slack をブラウザでログインする操作は行わない**（セキュリティ警告のため）。

## 役割分担

| 担当 | 内容 |
|------|------|
| **リポジトリ（本ドキュメント）** | `docker-compose.yml`、`.env` 例、`deploy/DEPLOY_GCP.md`、`deploy/CLINE_PROMPTS.md` |
| **Cline（あなたがプロンプトを渡す）** | gcloud / SSH / nginx / certbot、**Google Cloud Console の OAuth クライアント設定**（リダイレクト URI 追加）※ |
| **あなた（人間）** | GCP / Google の**ログイン**、**料金・本番 URL の最終承認**、必要なら **iPhone ショートカットの URL 編集** |
| **Slack** | **ブラウザログインはしない**。既存の Bot / App トークンを `.env` に載せるだけ。 |

※ OAuth クライアントは Google Cloud Console（Calendar API 用）であり、Slack のログインとは別です。

## 追加・変更する成果物（承認後に固定）

- `deploy/CLINE_PROMPTS.md` … Cline に渡すプロンプト集
- 本ファイル … 計画の記録

## リソース方針

- ローカル Mac で **Docker イメージのフルビルドを連発しない**（CI や VM 上でビルドする前提）。
- ドキュメントは **必要最小限の手順**に留める。

## 承認

**承認済み（実行フェーズへ移行）。**

- **高解像度の一括手順:** [`deploy/CLINE_FULL_RUNBOOK.md`](./CLINE_FULL_RUNBOOK.md)
- **手足への最終指令書:** [`deploy/CLINE_START_HERE.txt`](./CLINE_START_HERE.txt)（`@deploy/CLINE_START_HERE.txt 実行開始`）
- **Cline に貼る最終プロンプト:** [`deploy/CLINE_FINAL_PROMPT.txt`](./CLINE_FINAL_PROMPT.txt)
- **一時ブラウザプロフィール:** [`deploy/scripts/browser-temp-profile.sh`](./scripts/browser-temp-profile.sh)（SingletonLock 回避）
