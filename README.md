# 📅 Mailendar (Smart AI Mail & Calendar)

Gmail 분석을 통해 일정과 할 일을 자동으로 추출하고 관리하는 **AI 비서 대시보드**입니다.
Upstage Solar LLM을 활용하여 모호한 메일을 분류하고 사용자에게 알림을 제공합니다.

## 🚀 주요 기능
- **AI 메일 분석**: 수신 이메일을 SCHEDULE, TASK, SPAM으로 자동 분류.
- **iOS 스타일 알림 배지**: 수동 확인이 필요한 메일 발생 시 트레이 아이콘 및 메뉴에 빨간 숫자 배지 표시.
- **통합 대시보드**: Google Calendar, Notion 일정, Gmail 분석 결과를 한 화면에서 관리.
- **AI 에이전트**: 채팅 인터페이스를 통해 이메일 답장 초안 작성 및 일정 요약 제공.

## 🛠️ 기술 스택
- **Language**: Python 3.11+
- **Frontend**: Streamlit
- **Backend/Logic**: PyQt6 (Background Worker), SQLite
- **AI**: Upstage Solar (OpenAI-compatible)
- **API**: Google Gmail/Calendar/Tasks API, Notion API

