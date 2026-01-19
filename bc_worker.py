import os
import json
import time
import datetime
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from PyQt6.QtCore import QThread, pyqtSignal

# 통합 설정 및 기범 팀원의 모듈 임포트
import config
from classify import classify_email
from db import upsert_email, set_classification, init_db, list_needs_review

class BackgroundWorker(QThread):
    notification_signal = pyqtSignal(str, str)
    review_count_signal = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        init_db()
        self.creds = self.authenticate_google()

    def authenticate_google(self):
        token_path = os.path.join(config.TOKEN_DIR, "token.json")
        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, config.SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_CLIENT_SECRETS_FILE, config.SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        return creds

    def fetch_notion_tasks(self):
        import requests
        url = f"https://api.notion.com/v1/databases/{config.NOTION_DATABASE_ID}/query"
        headers = {"Authorization": f"Bearer {config.NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
        today_str = datetime.date.today().isoformat()
        filter_payload = {"filter": {"property": "Date", "date": {"equals": today_str}}}
        try:
            response = requests.post(url, headers=headers, json=filter_payload)
            pages = response.json().get('results', [])
            results = []
            for p in pages:
                props = p['properties']
                title = props['이름']['title'][0]['plain_text'] if props.get('이름') and props['이름']['title'] else "제목 없음"
                date_prop = props.get('Date', {}).get('date')
                start_time = date_prop.get('start', '') if date_prop else ''
                results.append({
                    "category": "SCHEDULE", "source": "Notion", "title": title,
                    "startTime": start_time, "displayTime": start_time.split('T')[1][:5] if 'T' in start_time else "종일"
                })
            return results
        except: return []

    def fetch_google_calendar(self, calendar_service):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        tomorrow = (datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=1), datetime.time.min)).astimezone(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
        events_result = calendar_service.events().list(calendarId='primary', timeMin=now, timeMax=tomorrow, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        return [{"category": "SCHEDULE", "source": "Google", "title": e.get('summary', '제목 없음'), "startTime": e['start'].get('dateTime', e['start'].get('date')), "displayTime": e['start'].get('dateTime', e['start'].get('date')).split('T')[1][:5] if 'T' in str(e['start'].get('dateTime')) else "종일"} for e in events]

    def run(self):
        if not self.creds: return
        gmail = build('gmail', 'v1', credentials=self.creds)
        calendar = build('calendar', 'v3', credentials=self.creds)

        while True:
            try:
                # 트레이 아이콘 숫자 업데이트 신호 발송
                self.review_count_signal.emit(len(list_needs_review()))

                today_data = self.fetch_google_calendar(calendar)
                today_data += self.fetch_notion_tasks()

                res = gmail.users().messages().list(userId='me', q=config.DEFAULT_GMAIL_QUERY).execute()
                for msg in res.get('messages', []):
                    m = gmail.users().messages().get(userId='me', id=msg['id']).execute()
                    headers = m.get('payload', {}).get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "제목 없음")
                    sender = next((h['value'] for h in headers if h['name'] == 'From'), "알 수 없음")
                    body = m.get('snippet', '')

                    # 1. AI 분석 수행
                    analysis = classify_email(sender, subject, body, body)
                    
                    # 2. [에러 해결 핵심 줄] 분석 결과에 email_id를 강제로 주입합니다.
                    analysis['email_id'] = msg['id']
                    
                    # 3. DB 저장 (원본 메일 + 분석 결과)
                    upsert_email({
                        "id": msg['id'], "thread_id": m.get('threadId'), "sender": sender,
                        "subject": subject, "date": datetime.datetime.now().isoformat(),
                        "snippet": body, "body": body, "created_at": datetime.datetime.now().isoformat()
                    })
                    set_classification(analysis) # 이제 'email_id' 키가 있어서 에러가 나지 않습니다.

                    # 4. 확정된 것만 타임라인 추가 및 캘린더 등록
                    if analysis.get('category') in ["SCHEDULE", "TASK"] and not analysis.get('needs_review'):
                        ext = analysis.get('extracted', {})
                        st = ext.get('startTime')
                        if analysis['category'] == "SCHEDULE" and st and 'T' in str(st):
                            event = {'summary': ext.get('title', subject), 'start': {'dateTime': st, 'timeZone': 'Asia/Seoul'}, 'end': {'dateTime': ext.get('endTime', st), 'timeZone': 'Asia/Seoul'}}
                            calendar.events().insert(calendarId='primary', body=event).execute()
                        
                        today_data.append({"category": analysis['category'], "title": ext.get('title', subject), "startTime": st, "displayTime": str(st).split('T')[1][:5] if st and 'T' in str(st) else "일정"})

                    self.notification_signal.emit(f"🔔 {analysis['category']} 발견", subject)
                    gmail.users().messages().batchModify(userId='me', body={'removeLabelIds': ['UNREAD'], 'ids': [msg['id']]}).execute()

                # 5. data.json 업데이트
                today_data.sort(key=lambda x: x.get('startTime') or '9999-12-31')
                with open('data.json', 'w', encoding='utf-8') as f:
                    json.dump(today_data, f, ensure_ascii=False, indent=4)

            except Exception as e: print(f"[루프 에러] {e}")
            time.sleep(30)