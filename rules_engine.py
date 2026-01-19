# -*- coding: utf-8 -*-

"""Rule-based sieve for email classification + urgency.

This is the USP-critical part:
1) Deterministic keyword scoring for SPAM/SCHEDULE/TASK
2) Urgency score (0-100)
3) Transparent debug: matched keywords + fired signals

The LLM stage is *secondary* and should never override very strong rule signals.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

from config import KST
from datetime_extract import clean_for_datetime, extract_event_times

# ----------------------------
# Keyword inventory (weights)
# ----------------------------

KEYWORD_WEIGHTS: Dict[str, Dict[str, int]] = {
    "SPAM": {
        "unsubscribe": 10,
        "수신거부": 10,
        "광고": 6,
        "홍보": 6,
        "마케팅": 6,
        "뉴스레터": 6,
        "구독": 4,
        "할인": 5,
        "특가": 5,
        "쿠폰": 5,
        "프로모션": 5,
        "이벤트": 3,
        "무료": 2,
        "webinar": 4,
        "웨비나": 4,
    },
    "SCHEDULE": {
        "일정": 4,
        "회의": 4,
        "미팅": 4,
        "면접": 5,
        "초대": 4,
        "참석": 3,
        "안내": 2,
        "발표": 3,
        "심사": 3,
        "세미나": 3,
        "워크샵": 3,
        "오리엔테이션": 3,
        "설명회": 3,
        "예약": 3,
        "zoom": 6,
        "google meet": 6,
        "meet.google.com": 6,
        "teams": 5,
        "webex": 5,
    },
    "TASK": {
        "회신": 6,
        "답신": 6,
        "답변": 5,
        "확인": 5,
        "요청": 5,
        "부탁": 4,
        "검토": 5,
        "승인": 5,
        "제출": 6,
        "피드백": 4,
        "수정": 4,
        "작성": 4,
        "공유": 3,
        "전달": 3,
        "자료": 3,
        "문의": 3,
        "조율": 4,
        "신청": 5,
        "등록": 4,
        "처리": 4,
        "마감": 5,
    },
}

URGENT_WORDS: Dict[str, int] = {
    "긴급": 25,
    "asap": 25,
    "즉시": 20,
    "최대한 빨리": 20,
    "중요": 10,
    "오늘까지": 25,
    "금일": 10,
    "내일": 10,
    "마감": 15,
    "기한": 15,
    "eod": 15,
}

ACTION_WORDS: Dict[str, int] = {
    "회신": 12,
    "확인": 10,
    "검토": 10,
    "승인": 10,
    "제출": 15,
    "답변": 10,
    "수정": 8,
    "작성": 8,
}

MEET_LINK_RE = re.compile(r"(meet\.google\.com|zoom\.us|teams\.microsoft\.com|webex\.com)", re.IGNORECASE)
UNSUB_RE = re.compile(r"\b(unsubscribe|opt\s*out|수신\s*거부)\b", re.IGNORECASE)

# Labeled lines
DATETIME_LABEL_RE = re.compile(r"(?im)^\s*(일시|시간|when|date)\s*[:：]", re.IGNORECASE)
LOCATION_LABEL_RE = re.compile(r"(?im)^\s*(장소|위치|location)\s*[:：]", re.IGNORECASE)

# deadline phrases like "오후 6시까지" / "18:00까지" / "12. 12.(금) 오후 6시까지"
DEADLINE_HINT_RE = re.compile(
    r"(?i)(오늘|금일|내일|\d{1,2}\s*[./-]\s*\d{1,2}|\d{4}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2})?\s*.*?(\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?\b).*?까지"
)


def _norm(text: str) -> str:
    return (text or "").replace("\u00a0", " ").lower()


def _count(text: str, kw: str) -> int:
    if not kw:
        return 0
    return _norm(text).count(kw.lower())


def keyword_score(text: str) -> Tuple[Dict[str, int], Dict[str, List[Dict[str, Any]]]]:
    """Return weighted scores + match details."""
    scores = {"SPAM": 0, "SCHEDULE": 0, "TASK": 0}
    matches: Dict[str, List[Dict[str, Any]]] = {"SPAM": [], "SCHEDULE": [], "TASK": []}

    for cat, table in KEYWORD_WEIGHTS.items():
        for kw, w in table.items():
            c = _count(text, kw)
            if c <= 0:
                continue
            pts = c * int(w)
            scores[cat] += pts
            matches[cat].append({"kw": kw, "count": c, "weight": w, "points": pts})

    # Sort matches by points desc
    for cat in matches:
        matches[cat].sort(key=lambda x: x.get("points", 0), reverse=True)

    return scores, matches


def _top2(scores: Dict[str, int]) -> Tuple[Tuple[str, int], Tuple[str, int]]:
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top1 = ordered[0] if ordered else ("TASK", 0)
    top2 = ordered[1] if len(ordered) > 1 else ("", 0)
    return top1, top2


def pick_category(scores: Dict[str, int], signals: Dict[str, Any]) -> Tuple[str, float]:
    """Return (category, rule_conf in 0..1)."""
    top1, top2 = _top2(scores)
    cat1, s1 = top1
    s2 = top2[1]
    margin = s1 - s2
    conf = 0.0 if s1 <= 0 else max(0.0, min(1.0, margin / max(1, s1)))

    # Guardrails
    if signals.get("unsubscribe") and scores["SPAM"] >= 12:
        return "SPAM", 0.95
    if signals.get("time_range"):
        return "SCHEDULE", 0.95

    # Threshold heuristics
    if scores["SPAM"] >= max(scores["SCHEDULE"], scores["TASK"]) + 10 and scores["SPAM"] >= 15:
        return "SPAM", max(conf, 0.85)
    if scores["SCHEDULE"] >= scores["TASK"] + 6 and scores["SCHEDULE"] >= 12:
        return "SCHEDULE", max(conf, 0.8)
    if scores["TASK"] >= 10:
        return "TASK", max(conf, 0.75)

    # Fallback: whichever is highest (TASK default if nothing)
    if s1 <= 0:
        return "TASK", 0.3
    return cat1, max(conf, 0.55)


def compute_urgency(text: str, event_start_iso: Optional[str]) -> int:
    """Compute urgency 0..100.

    - Strong boost for explicit deadlines (..까지)
    - Boost for action verbs
    - Boost for urgent words
    - If schedule start is near now, raise urgency
    """
    t = _norm(text)

    score = 0

    # Explicit urgent markers
    for w, pts in URGENT_WORDS.items():
        if w.lower() in t:
            score += int(pts)

    # Action markers
    for w, pts in ACTION_WORDS.items():
        if w.lower() in t:
            score += int(pts)

    # Deadline pattern
    if DEADLINE_HINT_RE.search(text or ""):
        score += 35

    # Time proximity (if event time exists)
    if event_start_iso:
        try:
            start = dt.datetime.fromisoformat(event_start_iso)
            now = dt.datetime.now(tz=KST)
            delta = start - now
            minutes = delta.total_seconds() / 60.0
            if 0 <= minutes <= 60:
                score += 45
            elif 0 <= minutes <= 120:
                score += 35
            elif 0 <= minutes <= 24 * 60:
                score += 20
        except Exception:
            pass

    return int(max(0, min(100, score)))


def analyze_email(subject: str, body: str) -> Dict[str, Any]:
    """Analyze email with rules.

    Returns a dict with:
    - scores: weighted category scores
    - matches: per-category matched keywords
    - signals: booleans for strong hints
    - urgency: 0..100
    - start_iso/end_iso/dt_source: extracted event time-range from body (if any)
    - predicted_category + rule_conf
    """
    subject = subject or ""
    body = body or ""

    text = f"{subject}\n{body}".strip()
    cleaned = clean_for_datetime(text)

    scores, matches = keyword_score(text)

    # Signals
    start_iso, end_iso, dt_src = extract_event_times(body)
    signals = {
        "unsubscribe": bool(UNSUB_RE.search(text)),
        "meet_link": bool(MEET_LINK_RE.search(text)),
        "datetime_label": bool(DATETIME_LABEL_RE.search(cleaned)),
        "location_label": bool(LOCATION_LABEL_RE.search(cleaned)),
        "time_range": bool(start_iso and end_iso),
        "deadline": bool(DEADLINE_HINT_RE.search(text)),
    }

    # Signal boosts
    if signals["unsubscribe"]:
        scores["SPAM"] += 15
    if signals["meet_link"]:
        scores["SCHEDULE"] += 15
    if signals["datetime_label"]:
        scores["SCHEDULE"] += 12
    if signals["location_label"]:
        scores["SCHEDULE"] += 6
    if signals["time_range"]:
        scores["SCHEDULE"] += 25

    predicted, rule_conf = pick_category(scores, signals)
    urgency = compute_urgency(text, start_iso)

    return {
        "scores": scores,
        "matches": matches,
        "signals": signals,
        "urgency": urgency,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "dt_source": dt_src,
        "predicted_category": predicted,
        "rule_conf": rule_conf,
    }
