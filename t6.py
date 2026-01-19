import streamlit as st
import pandas as pd
import json
import os
from streamlit_autorefresh import st_autorefresh
from db import list_needs_review, set_classification, init_db
from calendar_tasks import create_event, create_task
from agent import general_chat

# --- 1. 페이지 설정 및 세션 초기화 (에러 방지) ---
st.set_page_config(page_title="Mailendar Dashboard", page_icon="📅", layout="wide")

if 'page' not in st.session_state: st.session_state.page = "Dashboard"
if 'menu_open' not in st.session_state: st.session_state.menu_open = False
if 'agent_minimized' not in st.session_state: st.session_state.agent_minimized = False
if 'messages' not in st.session_state: st.session_state.messages = []

init_db()
st_autorefresh(interval=20 * 1000, key="data_refresh")

# --- 2. 데이터 로드 ---
def load_real_data():
    if os.path.exists('data.json'):
        try:
            with open('data.json', 'r', encoding='utf-8') as f: return json.load(f)
        except: return []
    return []

real_data = load_real_data()

# --- 3. 헤더 및 디자인 ---
st.markdown("<style>.logo-text { font-size: 26px; font-weight: bold; color: #E74C3C; }</style>", unsafe_allow_html=True)
h_left, h_right = st.columns([5, 5])
with h_left: st.markdown(f'<p class="logo-text">MAILENDAR | {st.session_state.page}</p>', unsafe_allow_html=True)
with h_right:
    i1, i2, i3, i4, i5, i6 = st.columns([5, 0.6, 0.6, 0.6, 0.6, 1.5])
    with i2: 
        if st.button("🔄"): st.rerun()
    with i5:
        if st.button("☰"): st.session_state.menu_open = not st.session_state.menu_open; st.rerun()

if st.session_state.menu_open:
    with st.container(border=True):
        cols = st.columns(4)
        items = [("🏠", "Dashboard"), ("📧", "Analysis"), ("⚙️", "Manual Review"), ("📊", "Reports")]
        for i, col in enumerate(cols):
            if col.button(f"{items[i][0]} {items[i][1]}"):
                st.session_state.page = items[i][1]; st.session_state.menu_open = False; st.rerun()

# --- 4. 메인 콘텐츠 ---
col_main, col_agent = st.columns([7, 3]) if not st.session_state.agent_minimized else st.columns([12, 0.01])

with col_main:
    if st.session_state.page == "Dashboard":
        st.markdown("### 🗓️ TODAY TIMETABLE")
        df = pd.DataFrame([{"시간": m.get('displayTime', '00:00'), "제목": m.get('title')} for m in real_data if m.get('category')=="SCHEDULE"])
        st.dataframe(df, width="stretch", hide_index=True)

    elif st.session_state.page == "Manual Review":
        st.markdown("### ⚙️ Manual Classification")
        items = list_needs_review()
        if not items: st.success("검토할 항목이 없습니다.")
        else:
            for item in items:
                with st.container(border=True):
                    st.write(f"**제목:** {item['subject']}")
                    try: ext = json.loads(item['extracted_json'])
                    except: ext = {}
                    
                    c1, c2, c3 = st.columns(3)
                    if c1.button("📅 일정 확정", key=f"s_{item['id']}"):
                        if ext.get('startTime') and ext.get('startTime') != "미정":
                            set_classification({"email_id": item['id'], "category": "SCHEDULE", "needs_review": False})
                            create_event(summary=ext.get('title', item['subject']), start_time=ext['startTime'], end_time=ext.get('endTime', ext['startTime']), description=ext.get('description', ''))
                            st.success("캘린더 등록 완료!"); st.rerun()
                        else: st.error("시간 정보가 없습니다.")
                    if c2.button("✅ 할 일 확정", key=f"t_{item['id']}"):
                        set_classification({"email_id": item['id'], "category": "TASK", "needs_review": False})
                        create_task(title=ext.get('title', item['subject']), notes=ext.get('description', ''))
                        st.success("할 일 등록 완료!"); st.rerun()
                    if c3.button("🗑️ 스팸", key=f"p_{item['id']}"):
                        set_classification({"email_id": item['id'], "category": "SPAM", "needs_review": False}); st.rerun()

with col_agent:
    with st.container(border=True):
        st.write("### 🤖 AI Agent")
        if prompt := st.chat_input("메시지 입력..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.session_state.messages.append({"role": "assistant", "content": general_chat(prompt)})
            st.rerun()