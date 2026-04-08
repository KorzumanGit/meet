"""
Slack 各ユーザーが自分の Google カレンダーを連携するための OAuth 受付サーバ。

別ターミナルで起動:
  python oauth_server.py

.env に OAUTH_PUBLIC_BASE_URL を設定（例: ngrok の https URL または http://127.0.0.1:8888）。

Google Cloud Console の OAuth クライアント「承認済みのリダイレクト URI」に次を追加:
  {OAUTH_PUBLIC_BASE_URL}/oauth2callback
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, redirect, request

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env", override=True)

from google_auth import (
    DEFAULT_CREDENTIALS,
    get_oauth_public_base_url,
    oauth_scopes,
    save_credentials_from_oauth_callback,
)
from google_auth_oauthlib.flow import Flow

_SLACK_USER_RE = re.compile(r"^U[A-Za-z0-9]+$")

app = Flask(__name__)


@app.route("/")
def root():
    """トップ URL（ブラウザでドメインを開いたときの案内）。"""
    return (
        "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'><title>meet</title></head><body>"
        "<h1>meet</h1>"
        "<p>OAuth / Shortcuts 用バックエンドです。</p>"
        "<ul>"
        "<li><a href='/health'>GET /health</a> — 疎通確認</li>"
        "<li>POST /api/meet — iOS ショートカット（要ヘッダ等）</li>"
        "<li>/oauth/start?slack_user_id=… — Google 連携（Slack ユーザー ID が必要）</li>"
        "</ul></body></html>",
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


@app.route("/oauth/start")
def oauth_start():
    slack_user_id = request.args.get("slack_user_id", "")
    if not _SLACK_USER_RE.match(slack_user_id):
        return "slack_user_id が不正です。", 400

    base = get_oauth_public_base_url()
    redirect_uri = f"{base}/oauth2callback"

    flow = Flow.from_client_secrets_file(
        str(DEFAULT_CREDENTIALS),
        oauth_scopes(),
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )
    # include_granted_scopes はスコープの組み合わせがずれて invalid_scope になることがあるため付けない
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=slack_user_id,
    )
    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    err = request.args.get("error")
    if err:
        return f"Google がエラーを返しました: {err}", 400

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        abort(400)

    if not _SLACK_USER_RE.match(state):
        return "state が不正です。", 400

    base = get_oauth_public_base_url()
    redirect_uri = f"{base}/oauth2callback"

    try:
        save_credentials_from_oauth_callback(
            code=code,
            slack_user_id=state,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        return f"トークン保存に失敗しました: {e}", 500

    return (
        "<html><body><h1>連携完了</h1>"
        "<p>このウィンドウを閉じて、Slack に戻り再度ボットにメッセージを送ってください。</p>"
        "</body></html>",
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


@app.route("/health")
def health():
    return "ok", 200


def _ios_shortcut_api_base() -> str:
    """Node の ios-shortcut-api（既定 3847）のベース URL。"""
    return os.environ.get("IOS_SHORTCUT_API_BASE", "http://127.0.0.1:3847").rstrip("/")


@app.route("/api/meet", methods=["POST", "OPTIONS"])
def proxy_ios_shortcut_meet():
    """
    iPhone ショートカット用 POST を、同一マシンの ios-shortcut-api に転送する。
    ngrok が 8888 のみのときも、公開 URL + /api/meet で Node 側に届く。
    """
    base = _ios_shortcut_api_base()
    url = f"{base}/api/meet"

    if request.method == "OPTIONS":
        return (
            "",
            204,
            {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-Api-Key, x-api-key, Authorization",
                "Access-Control-Max-Age": "86400",
            },
        )

    headers: dict[str, str] = {}
    ct = request.headers.get("Content-Type")
    headers["Content-Type"] = ct if ct else "application/json"
    for k in ("X-Api-Key", "x-api-key"):
        if k in request.headers:
            headers["X-Api-Key"] = request.headers[k]
            break

    try:
        req = urllib.request.Request(
            url,
            data=request.get_data(),
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
            out = Response(body, status=r.status)
            ct_out = r.headers.get("Content-Type", "application/json; charset=utf-8")
            out.headers["Content-Type"] = ct_out
            out.headers["Access-Control-Allow-Origin"] = "*"
            return out
    except urllib.error.HTTPError as e:
        body = e.read()
        out = Response(body, status=e.code)
        ct_err = "application/json; charset=utf-8"
        if e.headers:
            h = e.headers.get("Content-Type")
            if h:
                ct_err = h
        out.headers["Content-Type"] = ct_err
        out.headers["Access-Control-Allow-Origin"] = "*"
        return out
    except urllib.error.URLError as e:
        msg = (
            f'{{"ok":false,"error":"ios-shortcut-api に接続できません。'
            f'{base} で npm start 済みか確認してください: {e!s}"}}'
        )
        return (
            msg,
            503,
            {
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*",
            },
        )


def main() -> None:
    port = int(os.environ.get("OAUTH_SERVER_PORT", "8888"))
    host = os.environ.get("OAUTH_SERVER_HOST", "127.0.0.1")
    print(f"OAuth サーバ: http://{host}:{port}/oauth/start?slack_user_id=U...", flush=True)
    print(f"リダイレクト URI を Google に登録: {get_oauth_public_base_url()}/oauth2callback", flush=True)
    print(
        "他の Mac / iPhone から連携する場合: このマシンで `ngrok http 8888` し、"
        ".env の OAUTH_PUBLIC_BASE_URL を ngrok の https URL に変更（REMOTE_SETUP.md 参照）。",
        flush=True,
    )
    print(
        f"iPhone ショートカット POST /api/meet → {_ios_shortcut_api_base()}/api/meet に転送（未起動だと 503）。",
        flush=True,
    )
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
