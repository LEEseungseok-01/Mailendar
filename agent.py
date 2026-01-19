# -*- coding: utf-8 -*-

"""AI Agent helpers.

- Daily briefing: uses n8n DAILY_BRIEF_PROMPT
- Reply draft: initial draft + iterative refinement (chat-style)

The UI keeps conversation state in st.session_state; these functions are stateless.
"""

import json
from typing import Any, Dict, List, Optional

from prompts import DAILY_BRIEF_PROMPT
from classify import upstage_chat


def generate_daily_brief(clean_events: List[Dict[str, Any]], clean_tasks: List[Dict[str, Any]]) -> str:
    prompt = DAILY_BRIEF_PROMPT.format(
        clean_events_json=json.dumps(clean_events, ensure_ascii=False),
        clean_tasks_json=json.dumps(clean_tasks, ensure_ascii=False),
    )
    messages = [
        {"role": "system", "content": "You are a helpful Korean 업무 비서. Markdown으로 보기 좋게 정리해라."},
        {"role": "user", "content": prompt},
    ]
    return upstage_chat(messages, temperature=0.2)


def generate_reply_draft(email_context: str, user_hint: str = "") -> str:
    """Generate an initial reply draft."""

    hint = (user_hint or "").strip()
    prompt = (
        "너는 업무 이메일 답장을 돕는 AI 비서다.\n"
        "아래 이메일에 대해 정중하고 간결한 한국어 답장 초안을 작성해라.\n"
        "중요: 이 앱은 이메일을 실제로 발송하지 않는다. 따라서 '발송 완료', '발송했습니다' 같은 표현을 절대 쓰지 마라.\n"
        "또한 사용자가 별도로 요청하지 않는 이상 '발송 완료' 같은 자동 문구/주석을 넣지 마라.\n"
        "상대가 요구한 행동(회신/자료/일 수락 여부 등)이 있다면 그것을 명확히 반영해라.\n"
        "불필요한 장황함은 피하고, 필요한 질문이 있으면 짧게 물어봐라.\n"
        "출력은 '답장 본문'만 제공해라.\n"
    )
    if hint:
        prompt += f"\n[추가 요청]\n{hint}\n"

    prompt += f"\n[이메일]\n{email_context}\n"

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt},
    ]
    return upstage_chat(messages, temperature=0.3)


def refine_reply_draft(email_context: str, current_draft: str, instruction: str) -> str:
    """Refine an existing draft using user's instruction."""

    instruction = (instruction or "").strip()
    if not instruction:
        return current_draft

    prompt = (
        "너는 업무 이메일 답장을 다듬는 AI 비서다.\n"
        "아래 '현재 초안'을 '사용자 요청'에 맞게 수정해라.\n"
        "중요: 이 앱은 이메일을 실제로 발송하지 않는다. 따라서 '발송 완료', '발송했습니다' 같은 표현을 절대 쓰지 마라.\n"
        "가능하면 전체를 다시 작성하되, 핵심 정보(일정/요청/확답)는 유지해라.\n"
        "출력은 '수정된 답장 본문'만 제공해라.\n\n"
        f"[이메일]\n{email_context}\n\n"
        f"[현재 초안]\n{current_draft}\n\n"
        f"[사용자 요청]\n{instruction}\n"
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt},
    ]
    return upstage_chat(messages, temperature=0.25)


def general_chat(
    user_message: str,
    email_context: Optional[str] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    tasks: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """General agent chat (lightweight).

    If email_context is provided, answer with that context. Optionally use today's events/tasks.
    """

    ctx_parts: List[str] = []
    if events is not None:
        ctx_parts.append("[오늘 일정]\n" + json.dumps(events, ensure_ascii=False))
    if tasks is not None:
        ctx_parts.append("[할 일]\n" + json.dumps(tasks, ensure_ascii=False))
    if email_context:
        ctx_parts.append("[선택 메일]\n" + email_context)

    ctx = "\n\n".join(ctx_parts)

    prompt = (
        "너는 스마트 메일함 대시보드의 AI 에이전트다.\n"
        "사용자의 질문에 한국어로 간결하게 답하되, 필요한 경우 bullet로 정리해라.\n"
        "모르는 내용은 추측하지 말고, 확인이 필요하다고 말해라.\n\n"
        f"{ctx}\n\n"
        f"[사용자 질문]\n{user_message}\n"
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt},
    ]
    return upstage_chat(messages, temperature=0.3)
