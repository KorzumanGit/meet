"""テキストからカレンダー＋Meet 作成までの共通処理。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from calendar_event import (
    create_event_with_meet,
    create_event_without_conference,
    extract_meet_url,
)
from google_auth import get_calendar_service
from intent_parser import (
    ensure_default_duration_if_needed,
    force_meeting_one_hour,
    force_task_thirty_minutes,
    is_meeting_meet_intent,
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
    slack_filtered_meeting: bool = False,
) -> ScheduleResult:
    """
    自然言語テキストを解釈し、Google Calendar に登録する。

    - 「タスク」または「予定」（かな含む）→ 30分・Meet なし
    - 上記以外かつミーティング系ワード（ミーティング・打ち合わせ・会議・Meet 等）→ 1時間・Meet 付き
    - それ以外 → 1時間・Meet なし（カレンダーの時間ブロックのみ）

    slack_user_id を渡すと、その Slack メンバー用に保存した Google トークンを使う（Slack 経由）。
    None のときは従来どおり単一の token.json（CLI）。

    slack_filtered_meeting=True（Slack でキーワード・日時フィルターを通過した依頼）のときは、
    タスクモードでない限り **必ず Meet 付きで作成**する（他ユーザーの言い回しで is_meeting_meet_intent が落ちるのを防ぐ）。
    """
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

    if slack_filtered_meeting:
        use_meet = not task_mode
    else:
        use_meet = (not task_mode) and is_meeting_meet_intent(stripped)

    if task_mode:
        start_iso, end_iso = force_task_thirty_minutes(start_iso)
        kind = "task"
    else:
        start_iso, end_iso = force_meeting_one_hour(start_iso)
        kind = "meeting" if use_meet else "calendar"

    service = get_calendar_service(slack_user_id=slack_user_id)
    if task_mode or not use_meet:
        event = create_event_without_conference(
            service,
            title=title,
            start_iso=start_iso,
            end_iso=end_iso,
        )
        meet_url = None
    else:
        event = create_event_with_meet(
            service,
            title=title,
            start_iso=start_iso,
            end_iso=end_iso,
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
