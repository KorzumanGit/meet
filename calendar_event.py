"""Google Calendar にイベントを作成し、Google Meet の URL を付与する。"""

from __future__ import annotations

import re
import uuid
from typing import Any

from googleapiclient.discovery import Resource

TIMEZONE = "Asia/Tokyo"

# Google カレンダー API のイベント色（5 = 黄）。ios-shortcut-api と揃える。
MEET_EVENT_COLOR_ID = "5"
# タスク枠（Meet なし）用（9 = 青）
TASK_EVENT_COLOR_ID = "9"


def create_event_with_meet(
    service: Resource,
    *,
    title: str,
    start_iso: str,
    end_iso: str,
    calendar_id: str = "primary",
    timezone: str = TIMEZONE,
) -> dict[str, Any]:
    """
    イベントを挿入し、conferenceData で Meet を生成する。
    Meet 生成には createRequest.requestId が必須。
    """
    request_id = uuid.uuid4().hex

    body: dict[str, Any] = {
        "summary": title,
        "colorId": MEET_EVENT_COLOR_ID,
        "start": {
            "dateTime": start_iso,
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_iso,
            "timeZone": timezone,
        },
        "conferenceData": {
            "createRequest": {
                "requestId": request_id,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    created = (
        service.events()
        .insert(
            calendarId=calendar_id,
            body=body,
            conferenceDataVersion=1,
        )
        .execute()
    )

    return created


def create_event_without_conference(
    service: Resource,
    *,
    title: str,
    start_iso: str,
    end_iso: str,
    calendar_id: str = "primary",
    timezone: str = TIMEZONE,
    color_id: str = TASK_EVENT_COLOR_ID,
) -> dict[str, Any]:
    """Meet リンクを付けず、カレンダーの時間ブロックのみ作成する。"""
    body: dict[str, Any] = {
        "summary": title,
        "colorId": color_id,
        "start": {
            "dateTime": start_iso,
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_iso,
            "timeZone": timezone,
        },
    }

    created = (
        service.events()
        .insert(
            calendarId=calendar_id,
            body=body,
        )
        .execute()
    )

    return created


def extract_meet_url(event: dict[str, Any]) -> str | None:
    """作成済みイベント dict から Google Meet の参加 URL（meet.google.com 等）を取り出す。"""
    top = event.get("hangoutLink")
    if isinstance(top, str) and top.strip():
        return top.strip()
    cd = event.get("conferenceData") or {}
    entry_points = cd.get("entryPoints") or []
    meet_host = re.compile(r"meet\.google\.com|meetings\.google\.com", re.I)
    for ep in entry_points:
        uri = ep.get("uri")
        if isinstance(uri, str) and uri.strip() and meet_host.search(uri):
            return uri.strip()
    for ep in entry_points:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return str(ep["uri"]).strip()
    hl = cd.get("hangoutLink")
    if isinstance(hl, str) and hl.strip():
        return hl.strip()
    return None
