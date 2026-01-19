# -*- coding: utf-8 -*-

"""Google Calendar / Tasks helpers.

Calendar
- list events (date range)
- create / update / delete event

Tasks
- list tasks
- create / update / complete / delete task

Why "timeRangeEmpty" happens
- Google Calendar events.list requires timeMin < timeMax.
- In UI we allow selecting a single day; we convert it to an *exclusive* timeMax
  (end_date + 1 day 00:00) so timeMax is never empty.
"""

import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

from config import KST
from google_api import get_google_service


# --------------------
# Common helpers
# --------------------


def _parse_iso(dt_str: str) -> Optional[dt.datetime]:
    if not dt_str:
        return None
    s = dt_str.strip()
    # datetime.fromisoformat doesn't accept 'Z'
    s = s.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def _coerce_valid_range(start_iso: str, end_iso: str) -> tuple[str, str, bool]:
    """Return (start_iso, end_iso, fixed).

    We prefer to be forgiving (avoid Calendar 400 'timeRangeEmpty'):
    - If end <= start, auto-fix to end = start + 1 hour.
    """
    st = _parse_iso(start_iso)
    en = _parse_iso(end_iso)
    if st is None or en is None:
        raise ValueError("startTime/endTime must be RFC3339 (e.g., 2026-01-16T10:00:00+09:00)")
    fixed = False
    if en <= st:
        en = st + dt.timedelta(hours=1)
        fixed = True
    return st.isoformat(), en.isoformat(), fixed


def date_range_to_time_min_max(start_date: dt.date, end_date: dt.date) -> Tuple[str, str]:
    """Convert date range to RFC3339 timeMin/timeMax.

    timeMin: start_date 00:00:00 (inclusive)
    timeMax: (end_date + 1 day) 00:00:00 (exclusive)
    """
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    time_min_dt = dt.datetime.combine(start_date, dt.time(0, 0, 0), tzinfo=KST)
    time_max_dt = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time(0, 0, 0), tzinfo=KST)

    # Always guarantee timeMax > timeMin
    if time_max_dt <= time_min_dt:
        time_max_dt = time_min_dt + dt.timedelta(days=1)

    return time_min_dt.isoformat(), time_max_dt.isoformat()


# --------------------
# Calendar
# --------------------


def fetch_events(time_min: str, time_max: str, max_results: int = 50) -> List[Dict[str, Any]]:
    if not time_min or not time_max:
        raise ValueError("timeMin/timeMax is required")

    cal = get_google_service("calendar", "v3")
    res = (
        cal.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        )
        .execute()
    )

    items = res.get("items", []) or []
    out: List[Dict[str, Any]] = []
    for it in items:
        start = it.get("start", {}).get("dateTime") or it.get("start", {}).get("date")
        end = it.get("end", {}).get("dateTime") or it.get("end", {}).get("date")
        out.append(
            {
                "id": it.get("id"),
                "summary": it.get("summary", "(no title)"),
                "htmlLink": it.get("htmlLink", ""),
                "location": it.get("location", ""),
                "description": it.get("description", ""),
                "start": start,
                "end": end,
            }
        )
    return out


def fetch_events_by_date_range(start_date: dt.date, end_date: dt.date, max_results: int = 50) -> List[Dict[str, Any]]:
    time_min, time_max = date_range_to_time_min_max(start_date, end_date)
    return fetch_events(time_min, time_max, max_results=max_results)


def fetch_today_events(max_results: int = 30) -> List[Dict[str, Any]]:
    today = dt.datetime.now(tz=KST).date()
    return fetch_events_by_date_range(today, today, max_results=max_results)


def create_event(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """Create a Calendar event from extracted fields.

    Required:
      - title
      - startTime (RFC3339)
      - endTime (RFC3339)
    """

    start_iso = (extracted.get("startTime") or "").strip()
    end_iso = (extracted.get("endTime") or "").strip()
    start_iso, end_iso, _fixed = _coerce_valid_range(start_iso, end_iso)

    cal = get_google_service("calendar", "v3")
    body = {
        "summary": extracted.get("title", "(no title)"),
        "location": extracted.get("location", ""),
        "description": extracted.get("description", ""),
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    return cal.events().insert(calendarId="primary", body=body).execute()


def update_event(
    event_id: str,
    summary: str,
    location: str,
    description: str,
    start_iso: str,
    end_iso: str,
) -> Dict[str, Any]:
    start_iso, end_iso, _fixed = _coerce_valid_range(start_iso, end_iso)

    cal = get_google_service("calendar", "v3")
    body = {
        "summary": summary,
        "location": location,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    return cal.events().patch(calendarId="primary", eventId=event_id, body=body).execute()


def delete_event(event_id: str) -> None:
    cal = get_google_service("calendar", "v3")
    cal.events().delete(calendarId="primary", eventId=event_id).execute()


def get_event(event_id: str) -> Dict[str, Any]:
    """Fetch a single Calendar event (for confirmation UI)."""
    cal = get_google_service("calendar", "v3")
    it = cal.events().get(calendarId="primary", eventId=event_id).execute()
    start = it.get("start", {}).get("dateTime") or it.get("start", {}).get("date")
    end = it.get("end", {}).get("dateTime") or it.get("end", {}).get("date")
    return {
        "id": it.get("id"),
        "summary": it.get("summary", "(no title)"),
        "htmlLink": it.get("htmlLink", ""),
        "location": it.get("location", ""),
        "description": it.get("description", ""),
        "start": start,
        "end": end,
    }


# --------------------
# Tasks
# --------------------


def _get_default_tasklist_id() -> str:
    tasks = get_google_service("tasks", "v1")
    lists = tasks.tasklists().list(maxResults=10).execute().get("items", []) or []
    if not lists:
        raise RuntimeError("No tasklist found")
    return lists[0]["id"]


def fetch_tasks(show_completed: bool = False, max_results: int = 50) -> Tuple[str, List[Dict[str, Any]]]:
    tasks = get_google_service("tasks", "v1")
    tasklist_id = _get_default_tasklist_id()
    res = tasks.tasks().list(tasklist=tasklist_id, showCompleted=show_completed, maxResults=max_results).execute()
    items = res.get("items", []) or []

    out: List[Dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "id": it.get("id"),
                "title": it.get("title", "(no title)"),
                "selfLink": it.get("selfLink", ""),
                "notes": it.get("notes", ""),
                "due": it.get("due", ""),
                "status": it.get("status", ""),
            }
        )
    return tasklist_id, out


def fetch_pending_tasks(max_results: int = 30) -> List[Dict[str, Any]]:
    _, items = fetch_tasks(show_completed=False, max_results=max_results)
    return [{"title": t["title"], "notes": t.get("notes", "")} for t in items]


def create_task(extracted: Dict[str, Any]) -> Dict[str, Any]:
    tasks = get_google_service("tasks", "v1")
    tasklist_id = _get_default_tasklist_id()
    body = {
        "title": extracted.get("title", "(no title)"),
        "notes": extracted.get("description", ""),
    }
    return tasks.tasks().insert(tasklist=tasklist_id, body=body).execute()


def update_task(task_id: str, title: str, notes: str, due: str = "") -> Dict[str, Any]:
    tasks = get_google_service("tasks", "v1")
    tasklist_id = _get_default_tasklist_id()
    body: Dict[str, Any] = {"title": title, "notes": notes}
    if due:
        body["due"] = due
    return tasks.tasks().patch(tasklist=tasklist_id, task=task_id, body=body).execute()


def complete_task(task_id: str) -> Dict[str, Any]:
    tasks = get_google_service("tasks", "v1")
    tasklist_id = _get_default_tasklist_id()
    body = {
        "status": "completed",
        "completed": dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat(),
    }
    return tasks.tasks().patch(tasklist=tasklist_id, task=task_id, body=body).execute()


def delete_task(task_id: str) -> None:
    tasks = get_google_service("tasks", "v1")
    tasklist_id = _get_default_tasklist_id()
    tasks.tasks().delete(tasklist=tasklist_id, task=task_id).execute()


def get_task(task_id: str) -> Dict[str, Any]:
    """Fetch a single Task (for confirmation UI)."""
    tasks = get_google_service("tasks", "v1")
    tasklist_id = _get_default_tasklist_id()
    it = tasks.tasks().get(tasklist=tasklist_id, task=task_id).execute()
    return {
        "id": it.get("id"),
        "title": it.get("title", "(no title)"),
        "selfLink": it.get("selfLink", ""),
        "notes": it.get("notes", ""),
        "due": it.get("due", ""),
        "status": it.get("status", ""),
    }


