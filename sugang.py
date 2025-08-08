#!/usr/bin/env python3
# ---------------------------------------------------------------------
# sugangonline.py — SNU 수강신청 실시간 모니터 (Streamlit + Selenium, 로컬 chromedriver)
#   • 과목코드/분반을 여러 개 등록하여 동시에 모니터링
#   • 과목코드·분반 입력 → "등록" 버튼으로 리스트에 추가, 각 항목 옆 "×" 버튼으로 즉시 삭제
#   • 기본 배열: 경쟁률(담은수/정원) 내림차순, 체크 해제 시 등록 순
#   • 과목 삭제나 정렬 토글 시 *이미 조회한 데이터*만 사용해 불필요한 재조회 방지
#   • 자동 새로고침 1–10 초 (활성화 시에만 주기적으로 재조회)
#   • 개설연도·학기 입력 제거 ‒ 상수(DEFAULT_YEAR, DEFAULT_SEM) 사용
#   • chromedriver는 /usr/bin/chromedriver 등 로컬 바이너리 직접 사용
# ---------------------------------------------------------------------

import os, re, shutil, streamlit as st
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
PROF_COL = 11                               # 11번째 열(0‑based) → 교수명
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

# ---------- 유틸 ----------

def _parse_int(txt: str) -> int:
    m = re.search(r"\d+", txt.replace(",", ""))
    return int(m.group()) if m else 0


def open_and_search(drv, subject: str):
    """SNU 수강신청 검색 페이지를 열고 과목코드로 조회"""
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
    """조회 결과 테이블에서 분반(cls) 행을 찾아 정보 추출"""
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


def fetch_course_data(subject: str, cls: str, headless: bool):
    """단일 과목 정보를 크롤링하여 딕셔너리 반환. 오류 시 'error' 포함"""
    drv = create_driver(headless)
    try:
        open_and_search(drv, subject)
        quota, current, title, prof = read_info(drv, cls)
    except Exception as e:
        return {"subject": subject, "cls": cls, "error": str(e)}
    finally:
        drv.quit()

    if quota is None:
        return {"subject": subject, "cls": cls, "error": "행을 찾지 못했습니다."}

    return {
        "subject": subject,
        "cls": cls,
        "quota": quota,
        "current": current,
        "title": title,
        "prof": prof,
        "ratio": (current / quota) if quota else 0,
    }

# ---------- 그래프 ----------

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

# 세션 상태 초기화
if "courses" not in st.session_state:
    st.session_state.courses = []                    # [{subject, cls}]
if "course_data" not in st.session_state:
    st.session_state.course_data = {}                # {(subject, cls): info dict}

st.title("SNU 수강신청 실시간 모니터")

with st.sidebar:
    st.subheader("검색 설정")
    subject_input = st.text_input("과목코드", value="", placeholder="예시: 445.206")
    cls_input     = st.text_input("분반", value="", placeholder="예시: 002")
    add_clicked   = st.button("등록", use_container_width=True)

    auto      = st.checkbox("자동 새로고침", True)
    interval  = st.slider("새로고침(초)", 1, 10, value=2)
    headless  = st.checkbox("Headless 모드", True)

    sort_by_ratio = st.checkbox("경쟁률 순 배열", True)

# ---------- 등록 처리 ----------
if add_clicked:
    subj = subject_input.strip()
    cls  = cls_input.strip()
    if not subj or not cls:
        st.warning("과목코드·분반을 모두 입력하세요.")
    elif any(c["subject"] == subj and c["cls"] == cls for c in st.session_state.courses):
        st.info("이미 등록된 과목입니다.")
    else:
        st.session_state.courses.append({"subject": subj, "cls": cls})
        with st.spinner("과목 정보를 불러오는 중..."):
            data = fetch_course_data(subj, cls, headless)
        st.session_state.course_data[(subj, cls)] = data
        st.success(f"{subj}-{cls} 등록 완료")

# ---------- 자동 새로고침 ----------
st_autorefresh = getattr(st, "autorefresh", None) or getattr(st, "st_autorefresh", None)
if auto and st_autorefresh:
    st_autorefresh(interval=int(interval) * 1000, key="auto_refresh")

# ---------- 메인 렌더 ----------

def render_courses():
    if not st.session_state.courses:
        st.info("사이드바에서 과목코드와 분반을 입력 후 '등록'을 눌러 과목을 추가하세요.")
        return

    results = []

    if auto:
        # 자동 새로고침이 켜져 있을 때만 모든 과목 재조회
        with st.spinner("과목 정보 갱신 중..."):
            for c in st.session_state.courses:
                key = (c["subject"], c["cls"])
                data = fetch_course_data(*key, headless)
                st.session_state.course_data[key] = data
                results.append(data)
    else:
        # 캐시된 데이터 재사용, 없으면 처음 한 번만 조회
        for c in st.session_state.courses:
            key = (c["subject"], c["cls"])
            if key not in st.session_state.course_data:
                with st.spinner("과목 정보를 불러오는 중..."):
                    st.session_state.course_data[key] = fetch_course_data(*key, headless)
            results.append(st.session_state.course_data[key])

    # 정렬
    if sort_by_ratio:
        results.sort(key=lambda x: x.get("ratio", 0), reverse=True)

    st.subheader(f"{DEFAULT_YEAR}-{SEM_NAME[DEFAULT_SEM]}")

    for res in results:
        cols = st.columns([1, 9])  # × 버튼, 내용
        with cols[0]:
            if st.button("×", key=f"del_{res['subject']}_{res['cls']}"):
                # courses 목록 및 캐시에서 모두 제거
                st.session_state.courses = [
                    c for c in st.session_state.courses if not (c["subject"] == res["subject"] and c["cls"] == res["cls"])
                ]
                st.session_state.course_data.pop((res["subject"], res["cls"]), None)
                st.experimental_rerun()
                st.stop()  # 삭제 직후 불필요한 코드 실행 방지
        with cols[1]:
            if "error" in res:
                st.error(f"{res['subject']}-{res['cls']}: {res['error']}")
            else:
                render_bar(res["title"], res["current"], res["quota"])
                status = "만석" if res["current"] >= res["quota"] else "여석 있음"
                pct_display = res["ratio"] * 100
                st.caption(
                    f"**상태:** {status}  |  **현재 학생 비율:** {pct_display:.0f}%  |  "
                    f"**{res['cls'] :0>3}분반**, {res['prof']}"
                )

render_courses()
