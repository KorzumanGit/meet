"""OpenAI で自然言語から件名・開始・終了時刻を JSON 抽出する。"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent / ".env")

TIMEZONE = "Asia/Tokyo"

SYSTEM_PROMPT = """あなたはカレンダー予定のパーサです。ユーザーが話した日本語（または混在テキスト）から、次のキーだけを持つ JSON を返してください。
キー:
- "title": 予定の件名（短く明確に）
- "start_iso": 開始日時。必ず ISO 8601 形式。タイムゾーンは {tz} のオフセットを付ける（例: 2026-04-04T15:00:00+09:00）
- "end_iso": 終了日時。同様に ISO 8601 + オフセット。

ルール:
- 現在の参照日時は user メッセージに含まれる「現在日時」に従う。
- 「明日」「来週の月曜」「午後3時」などは、その参照日時とタイムゾーン {tz} で解釈する。
- 「5日の16時」のように月が省略され「N日」だけある場合は、参照日時から見てこれから最も近い未来の「当月または翌月のN日」を開始日とする（当日がN日より後なら翌月のN日）。件名（title）からは「N日の」「N日」や日付部分を除き、人名・会議内容だけを残す。
- 「火曜」「火曜日」など曜日だけの場合は、参照日時より後で最も近いその曜日を開始日とする。
- 終了時刻が明示されていない場合は、開始からちょうど1時間後とする。
- 日付だけで時刻がない場合は、開始 09:00、終了 10:00 とする（終了も1時間後）。
- 省略語は会議・打ち合わせと同義として解釈し、件名（title）には「ミーティング」「打ち合わせ」など自然な日本語に展開する。
  例: mt / MT / mtg / MTG / meeting → meeting・ミーティング・打ち合わせ。
  例: 「明日の15時から企画とmt」→ 件名は「企画ミーティング」や「企画のミーティング」など意味が通る形にする。
- 不明な部分は推測で補うが、件名が空なら「（無題）」とする。
- JSON 以外の文字は出力しない。
"""


def _now_iso(tz: ZoneInfo) -> str:
    return datetime.now(tz).isoformat(timespec="seconds")


_MEETING_MEET_RE = re.compile(
    r"ミーティング|打ち合わせ|会議|Google\s*Meet|ミーツ|Meets|Meet|MEET|meet|MTG|mtg|Zoom|zoom|ズーム|"
    r"オンライン会議|Web会議|Teams|teams|Webミーティング|ウェブミーティング",
    re.IGNORECASE,
)

# 「スケジュールを入れて」だけ予定語が無い場合もタスク枠（30分）に寄せる
_SCHEDULE_TASK_PHRASE_RE = re.compile(
    r"(?:スケジュール|すけじゅーる)\s*(?:を\s*)?(?:入れて|追加して|登録して|いれて)",
)


def is_task_calendar_intent(user_text: str) -> bool:
    """
    発話に「タスク」または「予定」が含まれる場合はタスク枠（Meet なし・30分）へ振り分ける。
    かな表記（たすく・よてい）も含める。
    「スケジュールを入れて」等、予定語なしでも同趣旨ならタスク枠とする。
    """
    t = unicodedata.normalize("NFKC", user_text.strip())
    if "タスク" in t or "たすく" in t:
        return True
    if "予定" in t or "よてい" in t:
        return True
    if _SCHEDULE_TASK_PHRASE_RE.search(t):
        return True
    return False


def is_meeting_meet_intent(user_text: str) -> bool:
    """
    Meet リンクを付けるのは「ミーティング系」の明示ワードがあるときのみ。
    （タスク／予定だけのときは False にしたいので、先に is_task_calendar_intent で除外する）
    """
    t = unicodedata.normalize("NFKC", user_text.strip())
    return bool(_MEETING_MEET_RE.search(t))


def sanitize_task_title(title: str, user_text: str) -> str:
    """
    「〇〇というタスクを入れて」のような発話から、カレンダー件名として短い作業名に整える。
    LLM が（無題）や長い件名を返した場合も、元テキストから復元を試みる。
    """
    raw = user_text.strip()
    t = (title or "").strip()

    def strip_task_phrases(s: str) -> str:
        s = re.sub(r"\s*というタスクを入れて\s*$", "", s)
        s = re.sub(r"\s*というタスク\s*$", "", s)
        s = re.sub(r"\s*のタスクを入れて\s*$", "", s)
        s = re.sub(r"\s*タスクを入れて\s*$", "", s)
        s = re.sub(r"\s*タスクを\s*$", "", s)
        s = re.sub(r"\s*という予定を入れて\s*$", "", s)
        s = re.sub(r"\s*の予定を入れて\s*$", "", s)
        s = re.sub(r"\s*予定を入れて\s*$", "", s)
        s = re.sub(r"\s*スケジュールを入れて\s*$", "", s)
        return s.strip()

    if not t or t == "（無題）":
        m = re.search(r"(.+?)\s*というタスク", raw)
        if m:
            return m.group(1).strip() or "（無題）"

    t = strip_task_phrases(t)
    if not t:
        m = re.search(r"(.+?)\s*というタスク", raw)
        if m:
            return m.group(1).strip() or "（無題）"
    return t or "（無題）"


def parse_intent_with_openai(
    user_text: str,
    *,
    model: str = "gpt-4o",
    timezone: str = TIMEZONE,
    task_mode: bool = False,
) -> dict[str, Any]:
    """テキストから title, start_iso, end_iso を含む dict を返す。"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("環境変数 OPENAI_API_KEY を設定してください。")

    tz = ZoneInfo(timezone)
    now_str = _now_iso(tz)
    client = OpenAI(api_key=api_key)

    system = SYSTEM_PROMPT.format(tz=timezone)
    user_content = f"現在日時（{timezone}）: {now_str}\n\n"
    if task_mode:
        user_content += (
            "【モード】タスク枠（Google Meet は使わない。カレンダーに 30 分の時間ブロックのみ）。"
            "件名（title）はユーザーが言った作業名・タスク名を短く明確に抽出してください。\n\n"
        )
    user_content += f"ユーザー発話:\n{user_text}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("OpenAI から空の応答が返りました。")

    data = json.loads(raw)
    for key in ("title", "start_iso", "end_iso"):
        if key not in data:
            raise ValueError(f"JSON に '{key}' がありません: {data}")

    # 検証: パース可能か
    datetime.fromisoformat(data["start_iso"].replace("Z", "+00:00"))
    datetime.fromisoformat(data["end_iso"].replace("Z", "+00:00"))

    return data


def ensure_default_duration_if_needed(
    start_iso: str,
    end_iso: str,
    *,
    default_hours: int = 1,
    timezone: str = TIMEZONE,
) -> tuple[str, str]:
    """
    LLM が同時刻などを返した場合の保険として、終了が開始以前なら +default_hours する。
    """
    tz = ZoneInfo(timezone)
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    if end <= start:
        end = start.astimezone(tz) + timedelta(hours=default_hours)
        return start_iso, end.isoformat(timespec="seconds")
    return start_iso, end_iso


def force_meeting_one_hour(start_iso: str, *, timezone: str = TIMEZONE) -> tuple[str, str]:
    """
    Meet 付き予定は常に 1 時間枠（終了 = 開始 + 1 時間）。LLM が 30 分などを返しても上書きする。
    """
    tz = ZoneInfo(timezone)
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)
    end = start + timedelta(hours=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def force_task_thirty_minutes(start_iso: str, *, timezone: str = TIMEZONE) -> tuple[str, str]:
    """
    タスク枠は常に 30 分（終了 = 開始 + 30 分）。Meet は付けない。
    """
    tz = ZoneInfo(timezone)
    start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)
    end = start + timedelta(minutes=30)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
