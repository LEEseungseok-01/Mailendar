# -*- coding: utf-8 -*-
import datetime as dt
import os
from dotenv import load_dotenv

# .env 파일의 내용을 로드합니다.
load_dotenv()

# 기본 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "smart_mailbox.db")
TOKEN_DIR = os.path.join(BASE_DIR, ".tokens")
os.makedirs(TOKEN_DIR, exist_ok=True)

# --- 환경 변수에서 설정값 가져오기 ---
# os.getenv("변수명", "기본값") 형태를 사용합니다.

# Upstage Solar AI 설정
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY", "").strip()
UPSTAGE_BASE_URL = os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1/solar").strip()
UPSTAGE_MODEL = os.getenv("UPSTAGE_MODEL", "solar-pro").strip()

# Notion 설정
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

# Google OAuth 설정
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "credentials.json").strip()
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify", 
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]

# Gmail fetch 설정
DEFAULT_GMAIL_QUERY = os.getenv("GMAIL_QUERY", "is:unread newer_than:1d").strip()
DEFAULT_GMAIL_MAX_RESULTS = int(os.getenv("GMAIL_MAX_RESULTS", "20"))

# 시간대 설정
KST = dt.timezone(dt.timedelta(hours=9))