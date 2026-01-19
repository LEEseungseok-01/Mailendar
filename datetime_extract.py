# -*- coding: utf-8 -*-

"""Datetime extraction for email bodies.

Why this exists
- Gmail messages often contain forwarded headers like:
    -----Original Message-----
    From: ...
    Sent: 2026-01-16 18:04
  If we regex-search the whole body, we can mistakenly treat that "Sent" time as the
  meeting time.

This module:
- Removes common header lines before extracting.
- Extracts date + time-range with simple heuristics.
- Returns RFC3339 start/end in Asia/Seoul (+09:00) timezone.

It's intentionally lightweight for an MVP (regex-based, no heavy NLP).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from config import KST


# ------------------------
# Cleaning helpers
# ------------------------

# Lines that look like forwarded/reply headers.
_HEADER_LINE_RE = re.compile(
    r"^\s*(from|to|cc|bcc|sent|date|subject)\s*:\s*.+$",
    re.IGNORECASE,
)
_KO_HEADER_LINE_RE = re.compile(
    r"^\s*(보낸사람|받는사람|참조|숨은참조|제목|보낸\s*날짜|보낸날짜|날짜|발신|수신)\s*: ?\s*.+$",
    re.IGNORECASE,
)

_SEPARATOR_RE = re.compile(
    r"^\s*(-{2,}\s*original message\s*-{2,}|-{2,}\s*원본\s*메시지\s*-{2,}|_{2,}|={2,})\s*$",
    re.IGNORECASE,
)


def clean_for_datetime(text: str) -> str:
    """Remove forwarded header-ish lines while keeping the actual content."""
    if not text:
        return ""

    lines = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip("\ufeff")
        if not line:
            lines.append("")
            continue
        if _SEPARATOR_RE.match(line):
            # Keep separator as blank to not glue unrelated sentences.
            lines.append("")
            continue
        if _HEADER_LINE_RE.match(line) or _KO_HEADER_LINE_RE.match(line):
            continue
        lines.append(raw)

    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ------------------------
# Extraction
# ------------------------

# Date patterns
# Korean emails often write dates with dots + spaces + weekday in parentheses:
#   "2025. 12. 19.(금) 14:00 ~ 17:00"
# Allow optional spaces around separators and tolerate trailing punctuation.
YMD_RE = re.compile(r"(?P<y>\d{4})\s*[./-]\s*(?P<m>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})")
MD_RE = re.compile(r"(?P<m>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})(?!\d)")
KO_MD_RE = re.compile(r"(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일")
REL_RE = re.compile(r"\b(오늘|내일|모레)\b")
WEEKDAY_RE = re.compile(r"\b(월|화|수|목|금|토|일)\s*요일\b")

# Time tokens (examples: 14:00, 9:30, 오후 2시, 오전10시반)
TIME_24_RE = re.compile(r"(?P<h>\d{1,2})\s*[:.]\s*(?P<mi>\d{2})")
TIME_KO_RE = re.compile(
    r"(?P<ampm>오전|오후)?\s*(?P<h>\d{1,2})\s*시(?:\s*(?P<mi>\d{1,2})\s*분)?\s*(?P<half>반)?"
)

# Range detection (match time tokens around connectors)
_TIME_TOKEN_STR = r"(?:오전|오후)?\s*\d{1,2}(?:\s*[:.]\s*\d{2}|\s*시(?:\s*\d{1,2}\s*분)?\s*(?:반)?)?"
RANGE_24_RE = re.compile(
    r"(?P<t1>\b\d{1,2}\s*[:.]\s*\d{2}\b)\s*(?:~|〜|–|—|-|to|부터)\s*(?P<t2>\b\d{1,2}\s*[:.]\s*\d{2}\b)(?:\s*까지)?",
    re.IGNORECASE,
)
RANGE_RE = re.compile(
    rf"(?P<t1>{_TIME_TOKEN_STR})\s*(?:~|〜|–|—|-|to|부터)\s*(?P<t2>{_TIME_TOKEN_STR})(?:\s*까지)?",
    re.IGNORECASE,
)


@dataclass
class ExtractedEvent:
    start: dt.datetime
    end: dt.datetime
    source: str


def _parse_date_token(token: str, base: dt.datetime) -> Optional[dt.date]:
    token = token.strip()

    m = YMD_RE.search(token)
    if m:
        y, mo, da = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        try:
            return dt.date(y, mo, da)
        except Exception:
            return None

    m = KO_MD_RE.search(token)
    if m:
        mo, da = int(m.group("m")), int(m.group("d"))
        try:
            return dt.date(base.year, mo, da)
        except Exception:
            return None

    m = MD_RE.search(token)
    if m:
        mo, da = int(m.group("m")), int(m.group("d"))
        try:
            return dt.date(base.year, mo, da)
        except Exception:
            return None

    m = REL_RE.search(token)
    if m:
        w = m.group(1)
        if w == "오늘":
            return base.date()
        if w == "내일":
            return (base + dt.timedelta(days=1)).date()
        if w == "모레":
            return (base + dt.timedelta(days=2)).date()

    m = WEEKDAY_RE.search(token)
    if m:
        wd_map = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
        target = wd_map[m.group(1)]
        delta = (target - base.weekday()) % 7
        return (base + dt.timedelta(days=delta)).date()

    return None


def _parse_time_token(token: str) -> Optional[int]:
    """Return minutes since midnight."""
    t = token.strip()

    m = TIME_24_RE.search(t)
    if m:
        h, mi = int(m.group("h")), int(m.group("mi"))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h * 60 + mi

    m = TIME_KO_RE.search(t)
    if m:
        ampm = (m.group("ampm") or "").strip()
        h = int(m.group("h"))
        mi = int(m.group("mi") or 0)
        if m.group("half") and mi == 0:
            mi = 30

        if 0 <= h <= 23 and 0 <= mi <= 59:
            if ampm == "오후" and h < 12:
                h += 12
            if ampm == "오전" and h == 12:
                h = 0
            return h * 60 + mi

    return None


def _build_dt(d: dt.date, minutes: int) -> dt.datetime:
    """Build timezone-aware datetime.

    Supports minute values that spill past midnight (e.g., 24:00 -> next-day 00:00).
    """
    extra_days = minutes // 1440
    minutes = minutes % 1440
    if extra_days:
        d = d + dt.timedelta(days=extra_days)
    h = minutes // 60
    mi = minutes % 60
    return dt.datetime(d.year, d.month, d.day, h, mi, tzinfo=KST)


def _ampm_hint(token: str) -> str:
    t = (token or "").strip()
    if "오후" in t:
        return "오후"
    if "오전" in t:
        return "오전"
    return ""


def _choose_t2_for_range(t1: int, t2_raw: int, ampm1: str, token2: str) -> int:
    """If token2 lacks AM/PM in Korean ranges like '오후 6시~9시', choose the most plausible t2.

    We evaluate candidates by duration and prefer a meeting-like duration (<=10 hours).
    """
    candidates = [t2_raw]

    # If start has 오후 and end token lacks am/pm, consider adding 12 hours.
    if ampm1 == "오후" and _ampm_hint(token2) == "" and t2_raw < 12 * 60:
        candidates.append(t2_raw + 12 * 60)

    best = candidates[0]
    best_dur = None
    for cand in candidates:
        end_total = cand
        # Move end forward until it's after start (handles crossing midnight).
        while end_total <= t1:
            end_total += 1440
        dur = end_total - t1
        # Prefer realistic meeting durations (5min ~ 10h)
        if 5 <= dur <= 600:
            if best_dur is None or dur < best_dur:
                best = cand
                best_dur = dur

    return best


def extract_event_times(text: str, base: Optional[dt.datetime] = None) -> Tuple[Optional[str], Optional[str], str]:
    """Extract best-effort event start/end.

    Returns (start_iso, end_iso, debug_source).
    - If nothing found: (None, None, "not_found")
    """
    if not text:
        return None, None, "not_found"

    base_dt = base or dt.datetime.now(tz=KST)
    cleaned = clean_for_datetime(text)

    current_date: Optional[dt.date] = None

    # Prefer lines explicitly labeled as schedule/time ("일시:", "시간:") so we don't pick
    # reply/forward metadata or response deadlines (e.g., "금일 오후 6시까지").
    all_lines = cleaned.split("\n")
    label_re = re.compile(r"(\b일시\b\s*[:：]|\b시간\b\s*[:：]|\b일정\b\s*[:：]|\bwhen\b\s*[:：]|\bdate\b\s*[:：])", re.IGNORECASE)
    labeled = [ln for ln in all_lines if label_re.search(ln)]
    others = [ln for ln in all_lines if ln not in labeled]

    for line in labeled + others:
        l = line.strip()
        if not l:
            continue

        d = _parse_date_token(l, base_dt)
        if d:
            current_date = d

        # 1) Pure 24-hour range first (avoids 'YYYY-MM-DD 14:00-16:00' being mis-read)
        m24 = RANGE_24_RE.search(l)
        if m24 and current_date:
            t1 = _parse_time_token(m24.group("t1"))
            t2_raw = _parse_time_token(m24.group("t2"))
            if t1 is not None and t2_raw is not None:
                start = _build_dt(current_date, t1)
                end_minutes = t2_raw
                if end_minutes <= t1:
                    end_minutes += 1440
                end = _build_dt(current_date, end_minutes)
                if end <= start:
                    end = start + dt.timedelta(hours=1)
                return start.isoformat(), end.isoformat(), f"line_range24:{l[:120]}"

        # 2) Generic range (Korean tokens, optional am/pm propagation)
        m = RANGE_RE.search(l)
        if m and current_date:
            t1 = _parse_time_token(m.group("t1"))
            t2_raw = _parse_time_token(m.group("t2"))
            if t1 is not None and t2_raw is not None:
                ampm1 = _ampm_hint(m.group("t1"))
                t2 = _choose_t2_for_range(t1=t1, t2_raw=t2_raw, ampm1=ampm1, token2=m.group("t2"))

                start = _build_dt(current_date, t1)
                end_minutes = t2
                # Cross-midnight handling
                if end_minutes <= t1:
                    end_minutes += 1440
                end = _build_dt(current_date, end_minutes)

                if end <= start:
                    end = start + dt.timedelta(hours=1)
                return start.isoformat(), end.isoformat(), f"line_range:{l[:120]}"

        if current_date:
            t = _parse_time_token(l)
            if t is not None:
                start = _build_dt(current_date, t)
                end = start + dt.timedelta(hours=1)
                return start.isoformat(), end.isoformat(), f"line_single:{l[:120]}"

    # Weak global search
    d = _parse_date_token(cleaned, base_dt)
    if d:
        times = []
        for tok in re.findall(
            r"(오전\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?\s*(?:반)?|오후\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?\s*(?:반)?|\d{1,2}\s*[:.]\s*\d{2}|\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?\s*(?:반)?)",
            cleaned,
        ):
            mi = _parse_time_token(tok)
            if mi is not None:
                times.append(mi)

        uniq = []
        for x in times:
            if x not in uniq:
                uniq.append(x)

        if len(uniq) >= 2:
            start = _build_dt(d, uniq[0])
            end = _build_dt(d, uniq[1])
            if end <= start:
                end = start + dt.timedelta(hours=1)
            return start.isoformat(), end.isoformat(), "global_date_two_times"
        if len(uniq) == 1:
            start = _build_dt(d, uniq[0])
            end = start + dt.timedelta(hours=1)
            return start.isoformat(), end.isoformat(), "global_date_one_time"

        # date-only => all-day event
        start = dt.datetime(d.year, d.month, d.day, 0, 0, tzinfo=KST)
        end = start + dt.timedelta(days=1)
        return start.isoformat(), end.isoformat(), "date_only_all_day"

    return None, None, "not_found"
