# -*- coding: utf-8 -*-

import json
import sqlite3
from typing import Any, Dict, List, Optional

from config import DB_PATH


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    return dict(row) if row is not None else {}


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                sender TEXT,
                subject TEXT,
                date TEXT,
                snippet TEXT,
                body TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classifications (
                email_id TEXT PRIMARY KEY,
                category TEXT,
                urgency INTEGER,
                rule_scores_json TEXT,
                llm_votes_json TEXT,
                confidence REAL,
                needs_review INTEGER,
                extracted_json TEXT,
                updated_at TEXT
            )
            """
        )
        # Optional links to created Google objects (for later update)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_links (
                email_id TEXT PRIMARY KEY,
                calendar_event_id TEXT,
                task_id TEXT,
                updated_at TEXT
            )
            """
        )


def upsert_email(email: Dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO emails (id, thread_id, sender, subject, date, snippet, body, created_at)
            VALUES (:id, :thread_id, :sender, :subject, :date, :snippet, :body, :created_at)
            ON CONFLICT(id) DO UPDATE SET
                thread_id=excluded.thread_id,
                sender=excluded.sender,
                subject=excluded.subject,
                date=excluded.date,
                snippet=excluded.snippet,
                body=excluded.body
            """,
            email,
        )


def list_recent_emails(limit: int = 30) -> List[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM emails ORDER BY date DESC LIMIT ?", (limit,)).fetchall())


def get_email(email_id: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()


def get_unclassified_ids(limit: int = 50) -> List[str]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT e.id FROM emails e
            LEFT JOIN classifications c ON e.id = c.email_id
            WHERE c.email_id IS NULL
            ORDER BY e.date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [r[0] for r in rows]


def get_classification(email_id: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM classifications WHERE email_id=?", (email_id,)).fetchone()


def set_classification(payload: Dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO classifications (
                email_id, category, urgency, rule_scores_json, llm_votes_json,
                confidence, needs_review, extracted_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email_id) DO UPDATE SET
                category=excluded.category,
                urgency=excluded.urgency,
                rule_scores_json=excluded.rule_scores_json,
                llm_votes_json=excluded.llm_votes_json,
                confidence=excluded.confidence,
                needs_review=excluded.needs_review,
                extracted_json=excluded.extracted_json,
                updated_at=excluded.updated_at
            """,
            (
                payload["email_id"],
                payload["category"],
                int(payload.get("urgency", 0)),
                json.dumps(payload.get("rule_scores", {}), ensure_ascii=False),
                json.dumps(payload.get("votes", []), ensure_ascii=False),
                float(payload.get("confidence", 0.0)),
                1 if payload.get("needs_review", False) else 0,
                json.dumps(payload.get("extracted", {}), ensure_ascii=False),
                payload.get("updated_at", ""),
            ),
        )


def list_needs_review(limit: int = 30) -> List[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT e.*, c.category, c.urgency, c.confidence, c.needs_review, c.extracted_json
                FROM emails e JOIN classifications c ON e.id=c.email_id
                WHERE c.needs_review=1
                ORDER BY c.urgency DESC, e.date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def list_urgent_tasks(urgent_threshold: int, limit: int = 20) -> List[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT e.*, c.urgency, c.extracted_json
                FROM emails e JOIN classifications c ON e.id=c.email_id
                WHERE c.category='TASK' AND c.urgency >= ? AND c.needs_review=0
                ORDER BY c.urgency DESC, e.date DESC
                LIMIT ?
                """,
                (urgent_threshold, limit),
            ).fetchall()
        )


def set_needs_review(email_id: str, needs_review: bool, extracted: Dict[str, Any], updated_at: str) -> None:
    """Update needs_review + extracted_json only (for user confirmation)."""
    with connect() as conn:
        conn.execute(
            """
            UPDATE classifications
            SET needs_review=?, extracted_json=?, updated_at=?
            WHERE email_id=?
            """,
            (1 if needs_review else 0, json.dumps(extracted, ensure_ascii=False), updated_at, email_id),
        )


def set_google_link(email_id: str, calendar_event_id: Optional[str], task_id: Optional[str], updated_at: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO google_links (email_id, calendar_event_id, task_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(email_id) DO UPDATE SET
                calendar_event_id=excluded.calendar_event_id,
                task_id=excluded.task_id,
                updated_at=excluded.updated_at
            """,
            (email_id, calendar_event_id, task_id, updated_at),
        )


def get_google_link(email_id: str) -> Dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM google_links WHERE email_id=?", (email_id,)).fetchone()
        return row_to_dict(row)


def list_google_links(limit: int = 50) -> List[sqlite3.Row]:
    """List recently linked Google objects (Calendar/Tasks) with email metadata."""
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT g.email_id, g.calendar_event_id, g.task_id, g.updated_at,
                       e.subject, e.sender, e.date
                FROM google_links g
                JOIN emails e ON e.id = g.email_id
                ORDER BY g.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
