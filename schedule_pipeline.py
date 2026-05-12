"""テキストからカレンダー＋Meet 作成までの共通処理。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from calendar_event import (
    MEET_EVENT_COLOR_ID,
    TASK_EVENT_COLOR_ID,
    create_event_with_meet,
    extract_meet_url,
)
from google_auth import get_calendar_service
from intent_parser import (
    ensure_default_duration_if_needed,
    force_meeting_one_hour,
    force_task_thirty_minutes,
    is_task_calendar_intent,
    parse_intent_with_openai,
    sanitize_task_title,
)


@dataclass
class ScheduleResult:
    title: str
    start_iso: str
    end_iso: str
    meet_url: str | None
    calendar_link: str
    event_summary: str
    kind: str  # "task" | "meeting" | "calendar"


def run_schedule_pipeline(
    user_text: str,
    *,
    model: str | None = None,
    slack_user_id: str | None = None,
    slack_filtered_meeting: bool = False,  # 互換のため残置（未使用）
) -> ScheduleResult:
    """
    自然言語テキストを解釈し、Google Calendar に登録する。

    仕様: 種別にかかわらず **すべて Google Meet URL を必ず発行する**。
    - 「タスク」または「予定」（かな含む）→ 30分 + Meet（色: 青）
    - それ以外 → 1時間 + Meet（色: 黄）

    slack_user_id を渡すと、その Slack メンバー用に保存した Google トークンを使う（Slack 経由）。
    None のときは従来どおり単一の token.json（CLI）。
    """
    del slack_filtered_meeting  # 旧仕様の引数（既存呼び出し側との互換のため受け取るだけ）

    model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")
    stripped = user_text.strip()
    task_mode = is_task_calendar_intent(stripped)

    parsed = parse_intent_with_openai(stripped, model=model, task_mode=task_mode)
    title = (parsed.get("title") or "").strip() or "（無題）"
    if task_mode:
        title = sanitize_task_title(title, stripped)
    start_iso = parsed["start_iso"]
    end_iso = parsed["end_iso"]
    start_iso, end_iso = ensure_default_duration_if_needed(start_iso, end_iso)

    if task_mode:
        start_iso, end_iso = force_task_thirty_minutes(start_iso)
        color_id = TASK_EVENT_COLOR_ID
        kind = "task"
    else:
        start_iso, end_iso = force_meeting_one_hour(start_iso)
        color_id = MEET_EVENT_COLOR_ID
        kind = "meeting"

    service = get_calendar_service(slack_user_id=slack_user_id)
    event = create_event_with_meet(
        service,
        title=title,
        start_iso=start_iso,
        end_iso=end_iso,
        color_id=color_id,
    )
    meet_url = extract_meet_url(event)

    calendar_link = str(event.get("htmlLink") or "")
    event_summary = str(event.get("summary") or title)

    return ScheduleResult(
        title=title,
        start_iso=start_iso,
        end_iso=end_iso,
        meet_url=meet_url,
        calendar_link=calendar_link,
        event_summary=event_summary,
        kind=kind,
    )
