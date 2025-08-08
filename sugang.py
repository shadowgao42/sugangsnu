#!/usr/bin/env python3
# ---------------------------------------------------------------------
# sugangonline.py — SNU 수강신청 실시간 모니터 (Streamlit + Selenium)
#   • 여러 과목 동시 모니터링: 과목코드/분반 입력 후 "등록"으로 추가, "×"로 삭제
#   • 기본 배열: 경쟁률 내림차순, 체크 해제 시 등록순
#   • 자동 새로고침 켜질 때만 재크롤링 → 삭제·정렬만으로는 캐시 사용
#   • Streamlit 버전별 rerun 함수 호환성 처리
# ---------------------------------------------------------------------

import os, re, shutil, streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ---------- 설정 ----------
DEFAULT_YEAR = 2025
DEFAULT_SEM = 3  # 3 → 2학기
SEM_VALUE = {1: "U000200001U000300001", 2: "U000200001U000300002", 3: "U000200002U000300001", 4: "U000200002U000300002"}
SEM_NAME = {1: "1학기", 2: "여름학기", 3: "2학기", 4: "겨울학기"}

TITLE_COL, CAP_COL, CURR_COL, PROF_COL = 6, 13, 14, 11
TIMEOUT = 10

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
        raise RuntimeError("chromedriver 경로를 찾지 못했습니다.")

    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1600,1000")
    return webdriver.Chrome(service=Service(drv_path), options=opts)

# ---------- 크롤링 util ----------

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
        str(DEFAULT_YEAR), SEM_VALUE[DEFAULT_SEM], subject.strip(),
    )


def read_info(drv, cls: str):
    WebDriverWait(drv, TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_basic tbody tr")))
    for tr in drv.find_elements(By.CSS_SELECTOR, "table.tbl_basic tbody tr"):
        tds = tr.find_elements(By.TAG_NAME, "td")
        if len(tds) <= CURR_COL:
            continue
        if any(td.text.strip() == cls for td in tds):
            cap_text = tds[CAP_COL].text
            m = re.search(r"\((\d+)\)", cap_text)
            quota = int(m.group(1)) if m else _parse_int(cap_text)
            current = _parse_int(tds[CURR_COL].text)
            title = tds[TITLE_COL].text.strip()
            prof = tds[PROF_COL].text.strip()
            return quota, current, title, prof
    return None, None, None, None


def fetch_course_data(subject: str, cls: str, headless: bool):
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

# ---------- 시각화 ----------

def render_bar(title: str, current: int, quota: int):
    pct = current / quota * 100 if quota else 0
    color = "#e53935" if current >= quota else "#1e88e5"
    st.markdown(
        f"""
        <div style='display:flex;align-items:center;gap:12px'>
          <div style='flex:1;position:relative;height:24px;background:#eee;border-radius:8px;overflow:hidden'>
            <div style='position:absolute;top:0;left:0;bottom:0;width:{pct:.2f}%;background:{color}'></div>
          </div>
          <span style='font-weight:600;white-space:nowrap'>{title} ({current}/{quota})</span>
        </div>""",
        unsafe_allow_html=True,
    )

# ---------- Streamlit UI ----------

st.set_page_config(page_title="SNU 수강신청 실시간 모니터", layout="wide")

# ---- 세션 상태 ----
if "courses" not in st.session_state:
    st.session_state.courses = []  # list of dicts
if "course_data" not in st.session_state:
    st.session_state.course_data = {}  # key: (subj, cls)

# ---- 사이드바 ----
st.title("SNU 수강신청 실시간 모니터")
with st.sidebar:
    st.subheader("검색 설정")
    subj_in = st.text_input("과목코드", placeholder="예시: 445.206")
    cls_in = st.text_input("분반", placeholder="예시: 002")
    add = st.button("등록", use_container_width=True)

    auto = st.checkbox("자동 새로고침(과목 등록 시 해제 권장)", False)
    interval = st.slider("새로고침(초)", 1, 10, 2)
    headless = st.checkbox("Headless 모드", True)

    sort_by_ratio = st.checkbox("경쟁률 순 배열", True)

# ---- 등록 처리 ----
if add:
    subj, cls = subj_in.strip(), cls_in.strip()
    if not subj or not cls:
        st.warning("과목코드·분반을 모두 입력하세요.")
    elif any(c["subject"] == subj and c["cls"] == cls for c in st.session_state.courses):
        st.info("이미 등록된 과목입니다.")
    else:
        with st.spinner("과목 정보를 불러오는 중..."):
            data = fetch_course_data(subj, cls, headless)
        st.session_state.courses.append({"subject": subj, "cls": cls})
        st.session_state.course_data[(subj, cls)] = data
        st.success(f"{subj}-{cls} 등록 완료")

# ---- 자동 새로고침 ----
st_autorefresh = getattr(st, "autorefresh", None) or getattr(st, "st_autorefresh", None)
if auto and st_autorefresh:
    st_autorefresh(interval=interval * 1000, key="__auto_refresh")

# ---- rerun helper ----
_rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)

# ---- 메인 렌더 ----

def render_courses():
    if not st.session_state.courses:
        st.info("사이드바에서 과목을 등록하세요.")
        return

    results = []
    if auto:
        with st.spinner("과목 정보 갱신 중..."):
            for c in st.session_state.courses:
                key = (c["subject"], c["cls"])
                st.session_state.course_data[key] = fetch_course_data(*key, headless)
                results.append(st.session_state.course_data[key])
    else:
        for c in st.session_state.courses:
            key = (c["subject"], c["cls"])
            if key not in st.session_state.course_data:
                with st.spinner("과목 정보를 불러오는 중..."):
                    st.session_state.course_data[key] = fetch_course_data(*key, headless)
            results.append(st.session_state.course_data[key])

    if sort_by_ratio:
        results.sort(key=lambda x: x.get("ratio", 0), reverse=True)

    st.subheader(f"{DEFAULT_YEAR}-{SEM_NAME[DEFAULT_SEM]}")

    for res in results:
        cols = st.columns([1, 9])
        del_clicked = cols[0].button("×", key=f"del_{res['subject']}_{res['cls']}")
        if del_clicked:
            st.session_state.courses = [c for c in st.session_state.courses if not (c["subject"] == res["subject"] and c["cls"] == res["cls"])]
            st.session_state.course_data.pop((res["subject"], res["cls"]), None)
            if _rerun_fn:
                _rerun_fn()
            else:
                st.stop()
        with cols[1]:
            if "error" in res:
                st.error(f"{res['subject']}-{res['cls']}: {res['error']}")
            else:
                render_bar(res["title"], res["current"], res["quota"])
                status = "만석" if res["current"] >= res["quota"] else "여석 있음"
                st.caption(
                    f"상태: {status} | 비율: {res['ratio']*100:.0f}% | 분반: {res['cls']:0>3} | 교수: {res['prof']}"
                )

render_courses()
