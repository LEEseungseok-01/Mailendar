# -*- coding: utf-8 -*-

"""Classification + extraction pipeline. (Updated for Manual Review Badge)

User-requested policy (updated)
- Stage 1: Rule-based scoring (keyword inventory + signals) -> category + urgency.
- Stage 2: ALWAYS run Upstage Solar once to re-classify + extract fields.
- Final decision is guarded: Vague times in SCHEDULE trigger needs_review = True.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import KST, UPSTAGE_API_KEY, UPSTAGE_BASE_URL, UPSTAGE_MODEL
from datetime_extract import extract_event_times
from prompts import MAIL_CLASSIFY_PROMPT
from rules_engine import analyze_email

# ----------------------------
# Simple field helpers
# ----------------------------

SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd)\s*[:：]\s*", re.IGNORECASE)
LOCATION_LINE_RE = re.compile(r"(?im)^\s*(?:장소|위치|location)\s*[:：]\s*(?P<loc>.+?)\s*$")


def now_iso() -> str:
    return dt.datetime.now(tz=KST).isoformat(timespec="seconds")


def clean_subject(subject: str) -> str:
    s = (subject or "").strip()
    for _ in range(6):
        ns = SUBJECT_PREFIX_RE.sub("", s).strip()
        if ns == s:
            break
        s = ns
    return s or (subject or "")


def extract_location(body: str) -> str:
    if not body:
        return ""
    m = LOCATION_LINE_RE.search(body)
    if not m:
        return ""
    loc = (m.group("loc") or "").strip()
    return loc.strip(" \t;,")


def extract_description_block(body: str) -> str:
    if not body:
        return ""
    lines = [ln.rstrip() for ln in body.replace("\r", "").split("\n")]
    start_markers = ["심사", "발표", "안내", "일시", "장소", "회의", "미팅", "세미나", "워크샵"]
    end_markers = ["회신", "문의", "연락", "담당", "문자", "전화", "감사"]

    start_idx = None
    for i, ln in enumerate(lines):
        l = ln.strip()
        if not l:
            continue
        if any(m in l for m in start_markers) and ("일시" in l or "장소" in l or "안내" in l or "발표" in l or "심사" in l):
            start_idx = i
            break

    if start_idx is None:
        return ""

    block: List[str] = []
    for ln in lines[start_idx : start_idx + 40]:
        l = ln.strip()
        if not l:
            if block and block[-1] != "":
                block.append("")
            continue
        if len(block) >= 8 and any(em in l for em in end_markers) and ("회신" in l or "문의" in l):
            break
        block.append(l)

    desc = "\n".join(block).strip()
    return desc if len(desc) >= 20 else ""


def build_email_context(sender: str, subject: str, body: str) -> str:
    body = (body or "").strip()
    if len(body) > 5000:
        body = body[:5000] + "\n... (truncated)"
    return f"[FROM]\n{sender}\n\n[SUBJECT]\n{subject}\n\n[BODY]\n{body}\n"


# ----------------------------
# Upstage Solar (single-pass refine)
# ----------------------------


def upstage_chat(messages: List[Dict[str, str]], temperature: float = 0.0, timeout: int = 60) -> str:
    if not UPSTAGE_API_KEY:
        raise RuntimeError("UPSTAGE_API_KEY is missing")

    url = f"{UPSTAGE_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {UPSTAGE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": UPSTAGE_MODEL,
        "messages": messages,
        "temperature": float(temperature),
        "top_p": 1,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def _extract_json_block(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"\{[\s\S]*\}", text)
    return m.group(0) if m else ""


def llm_refine(email_context: str, rule_summary: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Always run once and return (parsed_json, raw_text)."""
    prompt = MAIL_CLASSIFY_PROMPT.format(email_context=email_context)
    rule_blob = json.dumps(rule_summary, ensure_ascii=False)

    system = (
        "You are an assistant that classifies Gmail emails. "
        "Return ONLY valid JSON. "
        "JSON schema: {"
        "\"category\": \"SCHEDULE|TASK|SPAM\", "
        "\"title\": string, "
        "\"description\": string, "
        "\"location\": string, "
        "\"startTime\": RFC3339 string or '미정', "
        "\"endTime\": RFC3339 string or '미정', "
        "\"needs_review\": boolean"
        "}."
    )

    user = f"[RULE_ANALYSIS_JSON]\n{rule_blob}\n\n[EMAIL]\n{prompt}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    raw = upstage_chat(messages, temperature=0.0)
    js = _extract_json_block(raw)
    try:
        parsed = json.loads(js) if js else {}
    except:
        parsed = {}
    
    return parsed if isinstance(parsed, dict) else {}, raw


# ----------------------------
# Merge policy (rule + LLM)
# ----------------------------


def _coerce_category(v: Any) -> str:
    c = (v or "").strip().upper()
    return c if c in ("SCHEDULE", "TASK", "SPAM") else ""


def merge_rule_llm(
    sender: str,
    subject: str,
    snippet: str,
    body: str,
    rule: Dict[str, Any],
    llm: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool, float]:
    """Return (extracted, needs_review, confidence)."""

    rule_scores = rule.get("scores") or {"SPAM": 0, "SCHEDULE": 0, "TASK": 0}
    signals = rule.get("signals") or {}
    rule_cat = _coerce_category(rule.get("predicted_category")) or "TASK"
    rule_conf = float(rule.get("rule_conf") or 0.0)
    llm_cat = _coerce_category(llm.get("category"))

    out: Dict[str, Any] = dict(llm) if isinstance(llm, dict) else {}
    out["title"] = (out.get("title") or clean_subject(subject)).strip()
    out["description"] = (out.get("description") or "").strip()
    out["location"] = (out.get("location") or "").strip()

    # Rule-based fill-ins
    if not out.get("location"):
        out["location"] = extract_location(body or "")
    if not out.get("description"):
        out["description"] = extract_description_block(body or "")

    # 시간 추출 우선순위
    r_st, r_en = rule.get("start_iso"), rule.get("end_iso")
    if r_st and r_en:
        out["startTime"], out["endTime"] = r_st, r_en
    else:
        # LLM이 미정이라고 했거나 추출을 못했다면 마지막 수단으로 정규식 추출 시도
        st = str(out.get("startTime", "")).strip()
        if not st or st == "미정":
            st2, en2, src2 = extract_event_times(body or "")
            if st2:
                out["startTime"], out["endTime"] = st2, en2
                out["_dt_source"] = src2

    # 최종 카테고리 결정
    final_cat = llm_cat or rule_cat

    # [중요 가드레일] 수동 검토(Badge) 판단 로직
    needs_review = llm.get("needs_review", False)
    
    if final_cat == "SCHEDULE":
        st_val = str(out.get("startTime", "")).strip()
        # 시간이 아예 없거나, '미정'이거나, ISO 형식(T)이 아니면 무조건 수동 검토 필요
        if not st_val or st_val == "미정" or "T" not in st_val:
            needs_review = True
            out["startTime"] = "미정"
            out["_guardrail"] = "vague_schedule_time"

    # 기타 가드레일
    if signals.get("unsubscribe") and rule_scores.get("SPAM", 0) >= 12:
        final_cat = "SPAM"
        needs_review = False

    out["category"] = final_cat
    
    # 신뢰도 계산
    conf = 0.6
    if llm_cat == rule_cat: conf = 0.85
    if signals.get("time_range"): conf = max(conf, 0.9)

    return out, bool(needs_review), float(conf)


def classify_email(
    sender: str,
    subject: str,
    snippet: str,
    body: str,
    enable_llm: bool = True,
    debug: bool = False,
) -> Dict[str, Any]:
    """Main entry: rule -> llm refine -> merge."""
    rule = analyze_email(subject=subject, body=body)

    llm_parsed: Dict[str, Any] = {}
    llm_raw = ""
    used_llm = False

    if enable_llm and UPSTAGE_API_KEY:
        used_llm = True
        ctx = build_email_context(sender, subject, body)
        rule_summary = {
            "predicted_category": rule.get("predicted_category"),
            "scores": rule.get("scores"),
            "signals": rule.get("signals"),
            "start_iso": rule.get("start_iso"),
        }
        try:
            llm_parsed, llm_raw = llm_refine(ctx, rule_summary=rule_summary)
        except Exception as e:
            llm_parsed = {"category": rule.get("predicted_category") or "TASK", "needs_review": True}
            llm_raw = str(e)
    else:
        llm_parsed = {"category": rule.get("predicted_category") or "TASK"}

    # Merge logic
    extracted, needs_review, conf = merge_rule_llm(sender, subject, snippet, body, rule, llm_parsed)

    # UI용 이유 태그
    reasons = []
    if used_llm: reasons.append("llm_refine")
    if extracted.get("_guardrail"): reasons.append(str(extracted.get("_guardrail")))
    extracted["_review_reason"] = ",".join(reasons)

    return {
        "category": extracted.get("category"),
        "urgency": int(rule.get("urgency") or 0),
        "rule_scores": rule.get("scores"),
        "votes": [{"parsed": llm_parsed, "raw": llm_raw}],
        "confidence": float(conf),
        "needs_review": bool(needs_review),
        "extracted": extracted,
    }