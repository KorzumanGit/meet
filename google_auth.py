"""Google Calendar API 用 OAuth2 認証（CLI 用単一 token / Slack ユーザー別 token）。"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from googleapiclient.discovery import build

_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def oauth_scopes() -> list[str]:
    """
    新規 OAuth（/oauth/start や fetch_token）で要求するスコープ。
    環境変数 GOOGLE_OAUTH_SCOPES にカンマ区切りで指定可能（例: 1つだけの URL）。
    未設定時は calendar.events のみ（予定作成に必要な最小）。
    full calendar が必要なら .env に
    GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/calendar
    """
    raw = (os.environ.get("GOOGLE_OAUTH_SCOPES") or "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return ["https://www.googleapis.com/auth/calendar.events"]


def _load_user_credentials(tok_path: Path) -> Credentials:
    """トークン JSON から復元（scopes はファイルのまま）。"""
    return Credentials.from_authorized_user_file(str(tok_path), scopes=None)


def _client_id_secret_from_credentials_json(cred_path: Path) -> tuple[str, str]:
    raw = json.loads(cred_path.read_text(encoding="utf-8"))
    inst = raw.get("installed") or raw.get("web") or {}
    return (inst.get("client_id") or "", inst.get("client_secret") or "")


def refresh_token_file_via_http(tok_path: Path, *, oauth_client_secrets: Path) -> None:
    """
    google-auth の refresh() は scope を付けてしまい invalid_scope になることがある。
    RFC 6749 どおり grant_type=refresh_token のみ送り、scope パラメータは付けない。
    """
    data = json.loads(tok_path.read_text(encoding="utf-8"))
    rt = data.get("refresh_token")
    cid = data.get("client_id") or ""
    csec = data.get("client_secret") or ""

    if (not cid or not csec) and oauth_client_secrets.is_file():
        oc, os_ = _client_id_secret_from_credentials_json(oauth_client_secrets)
        cid = cid or oc
        csec = csec or os_

    if not rt or not cid or not csec:
        raise RuntimeError(
            "Google トークンに refresh_token と client_id/secret がありません。"
            "OAuth 連携をやり直してください。"
        )

    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": cid,
            "client_secret": csec,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        _GOOGLE_TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_txt = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Google トークン更新が HTTP {e.code} で失敗しました: {err_txt}"
        ) from e

    if "access_token" not in payload:
        raise RuntimeError(f"想定外のトークン応答: {payload}")

    data["token"] = payload["access_token"]
    data.setdefault("token_uri", _GOOGLE_TOKEN_ENDPOINT)
    data["client_id"] = cid
    data["client_secret"] = csec

    expires_in = int(payload.get("expires_in", 3600))
    exp = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 120))
    data["expiry"] = exp.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

    sc = payload.get("scope")
    if sc:
        data["scopes"] = sc.split() if isinstance(sc, str) else list(sc)

    tok_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


_ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = _ROOT / "credentials.json"
DEFAULT_TOKEN = _ROOT / "token.json"
TOKEN_DIR = _ROOT / "data" / "google_tokens"


class GoogleAuthRequired(Exception):
    """Slack ユーザー用の Google トークンがまだ無い。"""

    def __init__(self, slack_user_id: str, authorize_url: str) -> None:
        self.slack_user_id = slack_user_id
        self.authorize_url = authorize_url
        super().__init__(
            f"Google カレンダー未連携: {slack_user_id}. 次の URL で許可してください: {authorize_url}"
        )


def _ensure_token_dir() -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)


def token_path_for_slack_user(slack_user_id: str) -> Path:
    _ensure_token_dir()
    if not re.match(r"^U[A-Za-z0-9]+$", slack_user_id):
        raise ValueError(f"不正な slack_user_id: {slack_user_id!r}")
    return TOKEN_DIR / f"{slack_user_id}.json"


def get_oauth_public_base_url() -> str:
    """Slack に貼る OAuth 開始 URL のベース（末尾スラッシュなし）。"""
    base = os.environ.get("OAUTH_PUBLIC_BASE_URL", "http://127.0.0.1:8888").rstrip("/")
    return base


def oauth_public_url_is_localhost() -> bool:
    """127.0.0.1 / localhost のとき True。他端末・iPhone では HTTPS 公開 URL に差し替えが必要。"""
    base = get_oauth_public_base_url().lower()
    return "127.0.0.1" in base or "localhost" in base or base.startswith("http://0.0.0.0")


def build_authorize_url_for_slack_user(slack_user_id: str) -> str:
    """ブラウザで開く OAuth 開始 URL（oauth_server.py が起動していること）。"""
    base = get_oauth_public_base_url()
    q = urllib.parse.urlencode({"slack_user_id": slack_user_id})
    return f"{base}/oauth/start?{q}"


def get_calendar_service(
    slack_user_id: str | None = None,
    credentials_path: Path | str | None = None,
    token_path: Path | str | None = None,
):
    """
    credentials.json を使い OAuth2 で認証し、Calendar API v3 の service を返す。

    slack_user_id を渡した場合は data/google_tokens/<user>.json を使用（Slack 各メンバー用）。
    未設定のときは従来どおり token.json（CLI / 単一ユーザー）。
    """
    cred_path = Path(credentials_path or os.environ.get("GOOGLE_CREDENTIALS", DEFAULT_CREDENTIALS))

    if slack_user_id:
        tok_path = Path(token_path or token_path_for_slack_user(slack_user_id))
    else:
        tok_path = Path(token_path or os.environ.get("GOOGLE_TOKEN", DEFAULT_TOKEN))

    if not cred_path.is_file():
        raise FileNotFoundError(
            f"Google OAuth の credentials が見つかりません: {cred_path}\n"
            "Google Cloud Console で OAuth クライアントを作成し、"
            "credentials.json をこのパスに配置してください。"
        )

    if slack_user_id and not tok_path.is_file():
        raise GoogleAuthRequired(slack_user_id, build_authorize_url_for_slack_user(slack_user_id))

    creds: Credentials | None = None
    if tok_path.is_file():
        creds = _load_user_credentials(tok_path)

    if not creds or not creds.valid:
        if creds and creds.refresh_token:
            try:
                refresh_token_file_via_http(tok_path, oauth_client_secrets=cred_path)
                creds = _load_user_credentials(tok_path)
            except Exception as e:
                err = str(e).lower()
                if "invalid_scope" in err or "invalid_grant" in err:
                    raise RuntimeError(
                        "Google トークンの更新に失敗しました。"
                        "OAuth 同意画面のスコープと credentials.json を確認し、"
                        "Slack に表示された OAuth リンクから連携し直してください。"
                        f" 詳細: {e}"
                    ) from e
                raise
            if not creds.valid:
                raise RuntimeError("トークン更新後も認証が無効です。OAuth 連携をやり直してください。")
        elif not slack_user_id:
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), oauth_scopes())
            creds = flow.run_local_server(port=0)
            tok_path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise GoogleAuthRequired(slack_user_id, build_authorize_url_for_slack_user(slack_user_id))

    return build("calendar", "v3", credentials=creds)


def save_credentials_from_oauth_callback(
    *,
    code: str,
    slack_user_id: str,
    redirect_uri: str,
    credentials_path: Path | None = None,
) -> Path:
    """
    Web OAuth コールバックで受け取った code をトークンに交換し、
    Slack ユーザー別ファイルに保存する。
    """
    cred_path = Path(credentials_path or os.environ.get("GOOGLE_CREDENTIALS", DEFAULT_CREDENTIALS))
    tok_path = token_path_for_slack_user(slack_user_id)

    flow = Flow.from_client_secrets_file(
        str(cred_path),
        oauth_scopes(),
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        if "invalid_scope" in str(e).lower():
            raise RuntimeError(
                "OAuth でトークン交換に失敗しました（invalid_scope）。"
                "Google Cloud の「OAuth 同意画面」に "
                "https://www.googleapis.com/auth/calendar.events を追加するか、"
                "meet/.env に GOOGLE_OAUTH_SCOPES=https://www.googleapis.com/auth/calendar を設定して、"
                "同意画面に同じスコープを追加したうえで再度 /oauth/start から連携してください。"
                f" 詳細: {e}"
            ) from e
        raise
    creds = flow.credentials
    tok_path.write_text(creds.to_json(), encoding="utf-8")
    return tok_path
