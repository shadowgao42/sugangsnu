#!/usr/bin/env python3
# ---------------------------------------------------------------------
# app.py — SNU 수강신청 실시간 모니터 (Streamlit + Selenium, 로컬 chromedriver)
#   • 과목코드/분반 입력 → 과목명과 (담은수/정원) 막대그래프
#   • 현재 ≥ 정원: 빨간색, 현재 < 정원: 파란색
#   • 자동 새로고침 1–10 초
#   • 개설연도·학기 입력 제거 ‒ 상수(DEFAULT_YEAR, DEFAULT_SEM) 사용
#   • chromedriver는 /usr/bin/chromedriver 등 로컬 바이너리 직접 사용
# ---------------------------------------------------------------------

import os, re, streamlit as st, shutil
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------- 기본 설정 ----------
DEFAULT_YEAR = 2025      # 고정 연도
DEFAULT_SEM  = 3         # 3 → 2학기

SEM_VALUE = {
    1: "U000200001U000300001",
    2: "U000200001U000300002",
    3: "U000200002U000300001",
    4: "U000200002U000300002",
}
SEM_NAME = {1: "1학기", 2: "여름학기", 3: "2학기", 4: "겨울학기"}

TITLE_COL, CAP_COL, CURR_COL = 6, 13, 14   # 표 인덱스
PROF_COL = 11                               # 11번째 열(0-based) → 교수명
TIMEOUT = 10  # Selenium 대기시간(s)

CHROMEDRIVER_CANDIDATES = [
    "/usr/bin/chromedriver",
    "/usr/local/bin/chromedriver",
    "/usr/lib/chromium/chromedriver",
    shutil.which("chromedriver"),
]

# ---------- 드라이버 ----------

def create_driver(headless: bool = True):
    drv_path = next((p for p in CHROMEDRIVER_CANDIDATES if p and os.path.exists(p)), None)
    if not drv_path:
        raise RuntimeError(
            "chromedriver 경로를 찾지 못했습니다. packages.txt에 chromium-driver가 설치돼 있는지 확인하세요."
        )

    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1600,1000")

    return webdriver.Chrome(service=Service(drv_path), options=opts)

# ---------- 페이지 조작 ----------

def _parse_int(txt: str) -> int:
    m = re.search(r"\d+", txt.replace(",", ""))
    return int(m.group()) if m else 0


def open_and_search(drv, subject: str):
    drv.get("https://shine.snu.ac.kr/uni/sugang/cc/cc100.action")
    WebDriverWait(drv, TIMEOUT).until(EC.presence_of_element_located((By.ID, "srchOpenSchyy")))
    drv.execute_script(
        """
        document.getElementById('srchOpenSchyy').value = arguments[0];
        document.getElementById('srchOpenShtm').value  = arguments[1];
        document.getElementById('srchSbjtCd').value    = arguments[2];
        fnInquiry();
        """,
        str(DEFAULT_YEAR),
        SEM_VALUE[DEFAULT_SEM],
        subject.strip(),
    )


def read_info(drv, cls: str):
    WebDriverWait(drv, TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_basic tbody tr"))
    )
    for tr in drv.find_elements(By.CSS_SELECTOR, "table.tbl_basic tbody tr"):
        tds = tr.find_elements(By.TAG_NAME, "td")
        if len(tds) <= CURR_COL:
            continue
        if any(td.text.strip() == cls.strip() for td in tds):
            cap_txt = tds[CAP_COL].text
            m = re.search(r"\((\d+)\)", cap_txt)
            quota = int(m.group(1)) if m else _parse_int(cap_txt)
            current = _parse_int(tds[CURR_COL].text)
            title = tds[TITLE_COL].text.strip()
            prof  = tds[PROF_COL].text.strip()
            return quota, current, title, prof
    return None, None, None, None

# ---------- 막대그래프 ----------

def render_bar(title: str, current: int, quota: int):
    pct = (current / quota * 100) if quota else 0
    color = "#e53935" if current >= quota else "#1e88e5"
    st.markdown(
        f"""
        <div style='display:flex;align-items:center;gap:12px'>
          <div style='flex:1;position:relative;height:24px;background:#eee;border-radius:8px;overflow:hidden'>
            <div style='position:absolute;top:0;left:0;bottom:0;width:{pct:.2f}%;background:{color}'></div>
          </div>
          <span style='font-weight:600;white-space:nowrap'>{title} ({current}/{quota})</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------- Streamlit UI ----------

st.set_page_config(page_title="SNU 수강신청 실시간 모니터", layout="wide")
st.title("SNU 수강신청 실시간 모니터")

with st.sidebar:
    st.subheader("검색 설정")
    subject = st.text_input("과목코드", value="", placeholder="예시: 445.206")
    cls     = st.text_input("분반", value="", placeholder="예시: 002")
    auto    = st.checkbox("자동 새로고침", True)
    interval = st.slider("새로고침(초)", 1, 10, value=2)
    headless = st.checkbox("Headless 모드", True)

# 자동 새로고침
st_autorefresh = getattr(st, "autorefresh", None) or getattr(st, "st_autorefresh", None)
if auto and st_autorefresh:
    st_autorefresh(interval=int(interval) * 1000, key="auto_refresh")

placeholder = st.empty()


def render():
    if not subject.strip() or not cls.strip():
        st.info("과목코드·분반을 입력하세요.")
        return

    drv = create_driver(headless)
    try:
        with st.spinner("조회 중..."):
            quota, current, title, prof = None, None, None, None
            open_and_search(drv, subject)
            quota, current, title, prof = read_info(drv, cls)
    except Exception as e:
        st.error(f"오류: {e}")
        drv.quit()
        return
    finally:
        drv.quit()

    if quota is None:
        st.error("행을 찾지 못했습니다. 입력을 확인하세요.")
        return

    st.subheader(f"{DEFAULT_YEAR}-{SEM_NAME[DEFAULT_SEM]}")
    render_bar(title, current, quota)

    status = "만석" if current >= quota else "여석 있음"
    pct_display = current / quota * 100 if quota else 0
    st.write(
        f"**상태:** {status}  |   **현재 학생 비율:** {pct_display:.0f}% <br>"
        f"**{cls.strip():0>3}분반** {prof}"
        unsafe_allow_html=True
    )


with placeholder.container():
    render()
