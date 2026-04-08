"""
Slack ボットがカレンダー処理を開始するかどうかの判定（メンションなし時の誤爆防止）。

1. 会議系キーワード
2. 具体的な日時シグナル（過去談義の除外）
3. チャンネルでは「冒頭付近」に日時があること（議事録・長文の末尾だけ日付、を避ける）
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ユーザー指定 + 実運用で同格の「ミーティング」
_MEETING_NOUN_PATTERNS = (
    r"\bmtg\b",
    r"(?<![A-Za-z])mt(?![A-Za-z])",  # mt 単体（英単語の一部にしない）
    "会議",
    "ミーティング",
    "打ち合わせ",
    "面談",
    "商談",
    "アポ",
)

# 日時・スケジュールの具体性（このいずれかが必要）
_DATETIME_SIGNAL_RE = re.compile(
    r"(?:"
    r"\d{1,2}\s*/\s*\d{1,2}"  # 4/10, 04/10
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日?"  # 4月10日
    r"|明日|明後日|明々後日|あした|あす"
    r"|今日|本日"
    r"|来週|今週"
    r"|[月火水木金土日]曜(?:日)?"
    r"|(?:午前|午後)\s*\d{1,2}"
    r"|\d{1,2}\s*:\s*\d{2}"
    r"|\d{1,2}\s*時"
    r")",
    re.IGNORECASE,
)

# 過去の出来事として読む冒頭（スケジュール依頼ではない）
_PAST_OPENING_RE = re.compile(
    r"^\s*(?:昨日|一昨日|おととい)[はの、，,]\s*",
    re.MULTILINE,
)
_PAST_WITH_MEETING_RE = re.compile(
    r"(?:昨日|一昨日|おととい)の(?:mt|mtg|会議|ミーティング|打ち合わせ|面談|商談|アポ)(?:は|を|が|で|と)",
    re.IGNORECASE,
)

# 「冒頭」の最大文字数（チャンネル・mpim）。これより後にだけ日時がある長文・議事録風を除外
_LEAD_WINDOW = 120


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", (text or "").strip())


def has_meeting_keyword(text: str) -> bool:
    """会議を連想させる名詞が含まれるか。"""
    t = _normalize(text)
    if not t:
        return False
    for p in _MEETING_NOUN_PATTERNS:
        if p.startswith("\\") or p.startswith("("):
            if re.search(p, t, re.IGNORECASE):
                return True
        elif p in t:
            return True
    return False


def has_datetime_signal(text: str) -> bool:
    """日時らしい表現が 1 つ以上あるか（必須ゲート用）。"""
    return bool(_DATETIME_SIGNAL_RE.search(_normalize(text)))


def looks_like_past_meeting_story(text: str) -> bool:
    """
    「昨日のmtは…」のような過去談義。スケジュール依頼として扱わない。
    """
    t = _normalize(text)
    if _PAST_OPENING_RE.match(t):
        return True
    if _PAST_WITH_MEETING_RE.search(t):
        return True
    return False


def _first_datetime_match_span(text: str) -> tuple[int, int] | None:
    m = _DATETIME_SIGNAL_RE.search(_normalize(text))
    if not m:
        return None
    return m.start(), m.end()


def datetime_in_lead_portion(text: str) -> bool:
    """
    依頼文としての「冒頭」に日時があるか。
    先頭 _LEAD_WINDOW 文字以内に日時シグナルが必要（1 行目が長くても同じ窓で判定）。
    """
    t = _normalize(text)
    if not t:
        return False
    head = t[:_LEAD_WINDOW]
    return bool(_DATETIME_SIGNAL_RE.search(head))


@dataclass(frozen=True)
class ScheduleTriggerDecision:
    ok: bool
    reason: str


def evaluate_schedule_trigger(
    text: str,
    *,
    is_dm: bool,
    mention_ok: bool,
) -> ScheduleTriggerDecision:
    """
    メンションあり → フィルター通過（ユーザー明示）。
    DM → キーワード + 日時 + 過去談義除外（冒頭制限は緩い）。
    チャンネル等・メンションなし → キーワード + 日時 + 過去談義除外 + 冒頭に日時。
    """
    t = _normalize(text)
    if not t:
        return ScheduleTriggerDecision(False, "empty_text")

    if mention_ok:
        return ScheduleTriggerDecision(True, "bot_mention_explicit")

    if not has_meeting_keyword(t):
        return ScheduleTriggerDecision(False, "no_meeting_keyword")

    if looks_like_past_meeting_story(t):
        return ScheduleTriggerDecision(False, "past_meeting_narrative")

    if not has_datetime_signal(t):
        return ScheduleTriggerDecision(False, "no_datetime_signal")

    if is_dm:
        return ScheduleTriggerDecision(True, "dm_keyword_datetime_ok")

    if not datetime_in_lead_portion(t):
        span = _first_datetime_match_span(t)
        pos = span[0] if span else -1
        return ScheduleTriggerDecision(
            False,
            f"datetime_not_in_lead(first_signal_at={pos})",
        )

    return ScheduleTriggerDecision(True, "channel_keyword_datetime_lead_ok")
