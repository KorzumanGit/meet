"""
Slack でメッセージ（テキスト・音声）を受け取り、同じスレッドに Meet URL を返す。

起動前に .env に以下を設定:
  SLACK_BOT_TOKEN=xoxb-...
  SLACK_APP_TOKEN=xapp-...   （Socket Mode 用）

Slack アプリ側:
  - OAuth: chat:write, channels:history, groups:history, im:history, mpim:history, files:read
  - Socket Mode をオン
  - DM: ボット宛にそのまま送る
  - 公開/プライベートチャンネル: ボットを招待。メンションなしでは
    「会議系キーワード（mt / mtg / 会議 / ミーティング / 打ち合わせ / 面談 / 商談 / アポ）」
    かつ「具体的な日時」かつ「冒頭付近に日時」などの条件を満たしたときのみ処理（slack_message_filters）。
    @ボット メンションなら条件免除。
  - Google カレンダーは Slack ユーザーごとに連携（初回は bot が OAuth 用 URL を返す）
  - 任意: .env の SCHEDULE_FORCE_CALENDAR_SLACK_USER_ID で「誰が送っても」その Slack ユーザーの Google カレンダーにだけ書く
  - OAuth 用に別途: python oauth_server.py（.env の OAUTH_PUBLIC_BASE_URL と Google のリダイレクト URI を一致させる）

起動: python slack_bot.py

【イベント購読】DM 用 message.im に加え、チャンネルで使うなら message.channels / message.groups も追加すること。

【DM で反応しないときの必須チェック】
1. Event Subscriptions で「Enable Events」を ON（Socket Mode でも必須）
2. Subscribe to bot events に message.im を追加（DM 用）※これが無いと DM は届かない
3. OAuth スコープに im:history と chat:write を入れ、ワークスペースに再インストール
4. この PC で slack_bot.py を起動したままにする
5. slack_bot.log に「Slackイベント受信 type=message」が出るか確認（出なければ 1〜3）
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

# slack_bolt より先に .env を読む（import 連鎖で環境が必要になる前に）
_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env", override=True)

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from audio_transcribe import transcribe_audio_file
from google_auth import GoogleAuthRequired, oauth_public_url_is_localhost
from schedule_pipeline import run_schedule_pipeline
from slack_message_filters import evaluate_schedule_trigger

_SLACK_UID_RE = re.compile(r"^U[A-Za-z0-9]+$")


def _calendar_slack_user_id_for_google(sender_slack_user_id: str) -> str:
    """
    Google カレンダーに書き込むときに使う Slack ユーザー ID。
    SCHEDULE_FORCE_CALENDAR_SLACK_USER_ID が設定されていれば常にそちら（全員分 daisuke のカレンダーに、など）。
    未設定ならメッセージ送信者（従来どおり）。
    """
    forced = os.environ.get("SCHEDULE_FORCE_CALENDAR_SLACK_USER_ID", "").strip()
    if forced and _SLACK_UID_RE.match(forced):
        return forced
    return sender_slack_user_id


# auth_test で取得（チャンネルではメンション必須の判定に使う）
_bot_user_id_cache: str | None = None


def _get_bot_user_id(client) -> str:
    global _bot_user_id_cache
    if _bot_user_id_cache is None:
        _bot_user_id_cache = str(client.auth_test()["user_id"])
    return _bot_user_id_cache


def _is_direct_message(event: dict) -> bool:
    """1:1 の DM（im）。mpim / 通常チャンネルは False。"""
    ct = event.get("channel_type")
    if ct == "im":
        return True
    ch = event.get("channel") or ""
    return ch.startswith("D")


def _event_contains_bot_mention(event: dict, bot_user_id: str) -> bool:
    """本文・blocks 内に <@BOT_USER_ID> 形式のメンションがあるか。"""
    needle = f"<@{bot_user_id}>"
    text = event.get("text") or ""
    if needle in text:
        return True
    blocks = event.get("blocks")
    if blocks:
        blob = json.dumps(blocks, ensure_ascii=False)
        if needle in blob:
            return True
        if f'"user_id": "{bot_user_id}"' in blob or f'"user_id":"{bot_user_id}"' in blob:
            return True
    return False


IGNORE_SUBTYPES = frozenset(
    {
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "group_join",
        "group_leave",
        "message_changed",
        "message_deleted",
        "tombstone",
        "pinned_item",
        "unpinned_item",
    }
)


def _text_from_blocks(blocks: object) -> str:
    """text が空のとき blocks からプレーンテキストを拾う（App Home 等）。"""
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []

    def walk_rich(elements: list) -> None:
        for el in elements or []:
            et = el.get("type")
            if et == "text":
                parts.append(el.get("text") or "")
            elif et in ("user", "usergroup", "channel", "emoji", "link"):
                continue
            elif "elements" in el:
                walk_rich(el.get("elements") or [])

    for block in blocks:
        if not isinstance(block, dict):
            continue
        bt = block.get("type")
        if bt == "section" and isinstance(block.get("text"), dict):
            parts.append(block["text"].get("text") or "")
        elif bt == "rich_text":
            walk_rich(block.get("elements") or [])

    return " ".join(parts).strip()


def _strip_slack_formatting(text: str) -> str:
    """ユーザー向け表示用に簡易的に整形（メンション等は残しても LLM は解釈可能）。"""
    t = text.strip()
    t = re.sub(r"<@[^>]+>", "", t)
    t = re.sub(r"<#[^|>]+\|([^>]+)>", r"\1", t)
    t = re.sub(r"<(https?://[^|>]+)\|[^>]+>", r"\1", t)
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
    return t.strip()


def _is_audio_file(mimetype: str, filetype: str, name: str) -> bool:
    mt = (mimetype or "").lower()
    ft = (filetype or "").lower()
    if mt.startswith("audio/"):
        return True
    if mt in ("video/webm", "application/ogg", "audio/ogg"):
        return True
    if ft in ("webm", "mp3", "m4a", "aac", "opus", "oga", "wav", "flac"):
        return True
    if name and Path(name).suffix.lower() in (".webm", ".mp3", ".m4a", ".wav", ".ogg", ".opus"):
        return True
    return False


def _download_slack_file(url: str, token: str, dest: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def _gather_input_text(event: dict) -> str | None:
    """メッセージ本文と添付音声から、パイプライン用のテキストを組み立てる。"""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    parts: list[str] = []

    raw = event.get("text") or ""
    if not raw.strip() and event.get("blocks"):
        raw = _text_from_blocks(event["blocks"])
    cleaned = _strip_slack_formatting(raw)
    if cleaned:
        parts.append(cleaned)

    for f in event.get("files") or []:
        mimetype = f.get("mimetype") or ""
        filetype = f.get("filetype") or ""
        name = f.get("name") or ""
        if not _is_audio_file(mimetype, filetype, name):
            continue
        url = f.get("url_private_download")
        if not url:
            continue
        suffix = Path(name).suffix or ".bin"
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = Path(tmp.name)
            try:
                _download_slack_file(url, token, tmp_path)
                tr = transcribe_audio_file(tmp_path)
                parts.append(tr)
            finally:
                tmp_path.unlink(missing_ok=True)
        except (urllib.error.URLError, OSError, RuntimeError, EnvironmentError) as e:
            parts.append(f"[音声の文字起こしに失敗: {e}]")

    if not parts:
        return None
    return "\n".join(parts)


def _reply_in_thread(client, channel: str, thread_ts: str, text: str) -> None:
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=text,
        unfurl_links=False,
        unfurl_media=False,
    )


app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


@app.middleware
def log_all_slack_events(req, resp, next):
    """届いているイベントを記録（届かない場合は Slack の購読設定が原因）。"""
    logger = logging.getLogger(__name__)
    try:
        body = getattr(req, "body", None) or {}
        if not isinstance(body, dict):
            body = {}
        ev = (body or {}).get("event") or {}
        et = ev.get("type")
        if et:
            logger.info(
                "Slackイベント受信 type=%s subtype=%s channel=%s user=%s text_len=%s",
                et,
                ev.get("subtype"),
                ev.get("channel"),
                ev.get("user"),
                len(ev.get("text") or ""),
            )
    except Exception as e:
        logger.warning("log_all_slack_events: %s", e)
    return next()


@app.event("message")
def on_message(event, client, logger, ack):
    """DM / チャンネル共通で evaluate_schedule_trigger。処理しない場合はログのみ。3 秒以内に ack。"""
    ack()

    if event.get("bot_id"):
        return
    st = event.get("subtype") or None
    if st in IGNORE_SUBTYPES:
        return
    if st is not None and st != "file_share":
        logger.info("message スキップ: subtype=%s", st)
        return

    channel = event.get("channel")
    if not channel or "ts" not in event:
        logger.info("message スキップ: channel/ts なし event=%s", event.keys())
        return

    try:
        bot_uid = _get_bot_user_id(client)
    except Exception as e:
        logger.exception("auth_test 失敗: %s", e)
        return

    user_text = _gather_input_text(event)
    if not user_text or not user_text.strip():
        logger.info(
            "message スキップ: 本文なし subtype=%s channel=%s text=%r blocks=%s",
            st,
            channel,
            (event.get("text") or "")[:80],
            bool(event.get("blocks")),
        )
        return

    slack_user_id = event.get("user")
    if not slack_user_id:
        logger.info("message スキップ: user なし")
        return

    is_dm = _is_direct_message(event)
    mention_ok = _event_contains_bot_mention(event, bot_uid)
    decision = evaluate_schedule_trigger(
        user_text.strip(),
        is_dm=is_dm,
        mention_ok=mention_ok,
    )
    if not decision.ok:
        logger.info(
            "schedule_trigger 無視: reason=%s is_dm=%s mention=%s preview=%r",
            decision.reason,
            is_dm,
            mention_ok,
            user_text.strip()[:160],
        )
        return

    logger.info(
        "schedule_trigger 処理開始: reason=%s is_dm=%s mention=%s preview=%r",
        decision.reason,
        is_dm,
        mention_ok,
        user_text.strip()[:160],
    )

    thread_ts = event.get("thread_ts") or event["ts"]

    try:
        _reply_in_thread(client, channel, thread_ts, "予定を作成しています…（少々お待ちください）")
    except Exception as e:
        logger.exception("chat_postMessage 失敗（処理中）: %s", e)
        return

    def worker() -> None:
        try:
            calendar_uid = _calendar_slack_user_id_for_google(slack_user_id)
            # @メンションのみの依頼は従来どおり本文で Meet 判定。フィルタールートは会議依頼なので Meet を付与
            result = run_schedule_pipeline(
                user_text,
                slack_user_id=calendar_uid,
                slack_filtered_meeting=not mention_ok,
            )
            lines = [
                f"*件名:* {result.event_summary}",
                f"*開始:* `{result.start_iso}`",
                f"*終了:* `{result.end_iso}`",
            ]
            if result.kind == "task":
                lines.append("*種別:* タスク（30分・Meet は発行していません）")
            elif result.kind == "calendar":
                lines.append("*種別:* カレンダーのみ（1時間・Meet は発行していません）")
            elif result.kind == "meeting":
                if result.meet_url:
                    lines.append(f"*Google Meet:* {result.meet_url}")
                else:
                    lines.append("*Google Meet:* （URL を取得できませんでした）")
            if result.calendar_link:
                lines.append(f"*カレンダー:* {result.calendar_link}")
            _reply_in_thread(client, channel, thread_ts, "\n".join(lines))
        except GoogleAuthRequired as e:
            msg = (
                "Google カレンダーがまだ連携されていません。次のリンクをブラウザで開き、"
                "*あなたの Google アカウント*で許可してください（自分のカレンダーに予定が作成されます）。\n"
                f"{e.authorize_url}"
            )
            if oauth_public_url_is_localhost():
                msg += (
                    "\n\n※ *iPhone や別の Mac* からも連携するには、OAuth 用の *HTTPS の公開 URL*（例: ngrok）が必要です。"
                    "管理者は REMOTE_SETUP.md の手順で .env の OAUTH_PUBLIC_BASE_URL を更新し、"
                    "Google Cloud の「承認済みのリダイレクト URI」に (公開URL)/oauth2callback を追加してください。"
                )
            try:
                _reply_in_thread(client, channel, thread_ts, msg)
            except Exception as e2:
                logger.exception("連携案内の送信に失敗: %s", e2)
        except Exception as e:
            logger.exception(
                "schedule_pipeline 失敗（Slack には返信しません） preview=%r",
                user_text.strip()[:120],
            )

    threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    log_path = _ROOT / "slack_bot.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    logging.getLogger("slack_bolt").setLevel(logging.INFO)
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)
    bot = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not bot or not app_token:
        raise SystemExit(
            ".env に SLACK_BOT_TOKEN と SLACK_APP_TOKEN を設定してください。\n"
            "Slack API でアプリを作成し、Bot User OAuth Token と App-Level Token（Socket Mode）を取得します。"
        )
    print("Slack ボットを起動しました（Socket Mode）。Ctrl+C で終了します。", flush=True)
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
