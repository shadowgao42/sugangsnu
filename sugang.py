import os, re, shutil, time, streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= Config =================
DEFAULT_YEAR = 2025
DEFAULT_SEM  = 3
SEM_VALUE = {1: "U000200001U000300001", 2: "U000200001U000300002", 3: "U000200002U000300001", 4: "U000200002U000300002"}
SEM_NAME  = {1: "1학기", 2: "여름학기", 3: "2학기", 4: "겨울학기"}
TITLE_COL, CAP_COL, CURR_COL, PROF_COL = 6, 13, 14, 11
TIMEOUT = 10
MAX_PAGES_TO_TRY = 100  # 페이지네이션 최대 시도 페이지

CHROMEDRIVER = [
    "/usr/bin/chromedriver",
    "/usr/local/bin/chromedriver",
    "/usr/lib/chromium/chromedriver",
    shutil.which("chromedriver"),
]

# ================ Driver ==================
def driver(headless=True):
    path = next((p for p in CHROMEDRIVER if p and os.path.exists(p)), None)
    if not path:
        raise RuntimeError("chromedriver not found")
    opt = webdriver.ChromeOptions()
    if headless:
        opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1600,1000")
    return webdriver.Chrome(service=Service(path), options=opt)

def _int(txt:str)->int:
    m = re.search(r"\d+", txt.replace(",",""))
    return int(m.group()) if m else 0

def open_search(drv, subj:str):
    drv.get("https://shine.snu.ac.kr/uni/sugang/cc/cc100.action")
    WebDriverWait(drv,TIMEOUT).until(EC.presence_of_element_located((By.ID,"srchOpenSchyy")))
    drv.execute_script(
        """
        document.getElementById('srchOpenSchyy').value = arguments[0];
        document.getElementById('srchOpenShtm').value  = arguments[1];
        document.getElementById('srchSbjtCd').value    = arguments[2];
        fnInquiry();
        """, str(DEFAULT_YEAR), SEM_VALUE[DEFAULT_SEM], subj.strip()
    )

def _scan_current_page(drv, cls:str):
    WebDriverWait(drv,TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR,"table.tbl_basic tbody tr")))
    for tr in drv.find_elements(By.CSS_SELECTOR,"table.tbl_basic tbody tr"):
        tds = tr.find_elements(By.TAG_NAME,"td")
        if len(tds) <= CURR_COL:
            continue
        if any(td.text.strip() == cls for td in tds):
            cap = tds[CAP_COL].text
            m = re.search(r"\((\d+)\)", cap)
            quota = int(m.group(1)) if m else _int(cap)
            current = _int(tds[CURR_COL].text)
            title = tds[TITLE_COL].text.strip()
            prof  = tds[PROF_COL].text.strip()
            return quota, current, title, prof
    return None

def _has_page(drv, page:int)->bool:
    return drv.execute_script(
        """
        const p = String(arguments[0]);
        const patterns = [
            "fnGotoPage(" + p + ")",
            "fnGotoPage('" + p + "')",
            'fnGotoPage("' + p + '")',
            "javascript:fnGotoPage(" + p + ")",
            "javascript:fnGotoPage('" + p + "')",
            'javascript:fnGotoPage("' + p + '")'
        ];
        return Array.from(document.querySelectorAll('a[href]'))
          .some(a => patterns.includes(a.getAttribute('href')));
        """, str(page)
    ) or False

def _goto_page(drv, page:int):
    # snapshot old tbody
    try:
        tbody = WebDriverWait(drv, TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_basic tbody"))
        )
        old_html = tbody.get_attribute("innerHTML")
    except Exception:
        old_html = None

    # try direct call
    direct_ok = True
    try:
        drv.execute_script("fnGotoPage(arguments[0]);", str(page))
    except Exception:
        direct_ok = False

    if not direct_ok:
        # fallback: find anchor by href variants and click via JS
        clicked = drv.execute_script(
            """
            const p = String(arguments[0]);
            const hrefs = [
              "javascript:fnGotoPage(" + p + ");",
              "javascript:fnGotoPage('" + p + "');",
              'javascript:fnGotoPage("' + p + '");',
              "fnGotoPage(" + p + ");",
              "fnGotoPage('" + p + "');",
              'fnGotoPage("' + p + '");'
            ];
            const a = Array.from(document.querySelectorAll('a[href]'))
              .find(x => hrefs.includes(x.getAttribute('href')));
            if (a) { a.click(); return true; }
            return false;
            """, str(page)
        )
        if not clicked:
            raise RuntimeError("해당 페이지 링크를 찾지 못했습니다.")

    WebDriverWait(drv, TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR,"table.tbl_basic tbody tr"))
    )
    if old_html is not None:
        t0 = time.time()
        while time.time() - t0 < TIMEOUT:
            try:
                new_html = drv.find_element(By.CSS_SELECTOR, "table.tbl_basic tbody").get_attribute("innerHTML")
                if new_html != old_html:
                    break
            except Exception:
                pass
            time.sleep(0.1)

def read_info(drv, cls:str):
    found = _scan_current_page(drv, cls)
    if found:
        return found
    page = 2
    while page <= MAX_PAGES_TO_TRY and _has_page(drv, page):
        try:
            _goto_page(drv, page)
        except Exception:
            break
        found = _scan_current_page(drv, cls)
        if found:
            return found
        page += 1
    return None, None, None, None

def fetch(subj:str, cls:str, headless:bool):
    drv = driver(headless)
    try:
        open_search(drv, subj)
        quota, current, title, prof = read_info(drv, cls)
    except Exception as e:
        return {"subject":subj,"cls":cls,"error":str(e)}
    finally:
        drv.quit()
    if quota is None:
        return {"subject":subj,"cls":cls,"error":"행을 찾지 못했습니다."}
    return {
        "subject":subj, "cls":cls,
        "quota":quota, "current":current,
        "title":title, "prof":prof,
        "ratio": current / quota if quota else 0
    }

# ================= UI ==================
st.set_page_config(page_title="SNU 수강신청 실시간 모니터", layout="wide")

# CSS (bars + control forms)
st.markdown("""
<style>
.bar-track {
  width: var(--bar-width, 520px);
  position: relative;
  height: 24px;
  background: #eee;
  border-radius: 8px;
  overflow: hidden;
}
.bar-fill { position:absolute; top:0; left:0; bottom:0; }
.bar-center {
  position:absolute; inset:0;
  display:flex; align-items:center; justify-content:center;
  font-weight:600; font-size:13px;
}
.course-title { font-weight: 600; }
@media (max-width: 640px) { .bar-track { width: 100% !important; } }
</style>
""", unsafe_allow_html=True)

# session state
if "courses" not in st.session_state: st.session_state.courses = []
if "data" not in st.session_state: st.session_state.data = {}
if "pending" not in st.session_state: st.session_state.pending = []
if "headless" not in st.session_state: st.session_state.headless = True
if "favorites" not in st.session_state: st.session_state.favorites = set()

rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
auto_key = "__auto_refresh"

st.title(f"SNU 수강신청 실시간 모니터 ({DEFAULT_YEAR}학년도 {SEM_NAME[DEFAULT_SEM]})")

with st.sidebar:
    st.header("설정")
    subj = st.text_input("과목코드", placeholder="예시: 445.206")
    cls  = st.text_input("분반", placeholder="예시: 002")
    add  = st.button("등록", use_container_width=True)
    refresh_clicked = st.button("🔄 수동 새로고침", use_container_width=True)
    auto = st.checkbox("자동 새로고침(과목 등록 시 해제 권장)", False)
    interval = st.slider("새로고침(초)", 1, 10, 5)
    st.session_state.headless = st.checkbox("Headless 모드", st.session_state.headless)
    sort_ratio = st.checkbox("채워진 비율 순 배열", True)

def _safe_id(*parts):
    s = "_".join(str(p) for p in parts)
    return re.sub(r"[^0-9a-zA-Z_-]+", "_", s)

# queue fetch rather than blocking
if add:
    s, c = subj.strip(), cls.strip()
    if not s or not c:
        st.warning("과목코드·분반을 모두 입력하세요.")
    elif any(x["subject"] == s and x["cls"] == c for x in st.session_state.courses) or (s, c) in st.session_state.pending:
        st.info("이미 등록된 과목이거나 로딩 중입니다.")
    else:
        st.session_state.pending.append((s, c))
        (getattr(st, "toast", None) or st.info)(f"{s}-{c} 데이터 로딩 시작")

# autorefresh
ar = getattr(st, "autorefresh", None) or getattr(st, "st_autorefresh", None)
if auto and ar:
    ar(interval=interval*1000, key=auto_key)

# progress bar
FIXED_BAR_PX = 520
def bar(curr:int, quota:int, filled_color:str):
    pct = curr / quota * 100 if quota else 0
    html = f"""
    <div class='bar-track' style='--bar-width:{FIXED_BAR_PX}px'>
        <div class='bar-fill' style='width:{pct:.2f}%; background:{filled_color};'></div>
        <div class='bar-center'>{curr}/{quota}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

def render():
    if not st.session_state.courses:
        st.info("사이드바에서 과목을 등록하세요.")
        return

    # Build (original_index, result) for stable sorting
    items = []
    for i, c in enumerate(st.session_state.courses):
        k = (c["subject"], c["cls"])
        items.append((i, st.session_state.data.get(k)))

    favs = st.session_state.favorites

    def sort_key(item):
        i, r = item
        if r is None:
            return (1, 0, i)
        fav_flag = 0 if (r['subject'], r['cls']) in favs else 1
        ratio = r.get("ratio", 0)
        ratio_key = -ratio if sort_ratio else 0
        return (fav_flag, ratio_key, i)

    items.sort(key=sort_key)

    for i, r in items:
        if r is None:
            st.info("데이터 로딩 중...")
            continue

        col = st.columns([2, 8])
        k = (r['subject'], r['cls'])
        safekey = _safe_id(r['subject'], r['cls'])

        # -------- Controls: st.form with two submit buttons, forced inline with zero gap --------
        with col[0]:
            fav_on = k in st.session_state.favorites
            wrap_id = f"ctl_{safekey}"
            st.markdown(f"<div id='{wrap_id}'>", unsafe_allow_html=True)
            with st.form(f"form_{safekey}", clear_on_submit=False):
                del_clicked = st.form_submit_button("×")
                fav_clicked = st.form_submit_button("★" if fav_on else "☆")
            st.markdown(f"""
<style>
#{wrap_id} form {{ display:inline-flex; align-items:center; gap:0 !important; }}
#{wrap_id} .stButton {{ display:inline-block !important; margin:0 !important; }}
#{wrap_id} .stButton>button {{
  width:36px !important; height:36px !important; padding:0 !important;
  border-radius:8px !important; font-size:18px !important; line-height:1 !important;
  border:1px solid #ccc !important; background:#fff !important; color:#111 !important;
}}
/* second button (favorite) coloring depending on state */
#{wrap_id} .stButton:nth-of-type(2)>button {{
  border-color: {('#ffe0b2' if fav_on else '#ccc')} !important;
  background: {('#fff3e0' if fav_on else '#fff')} !important;
  color: {('#fb8c00' if fav_on else '#111')} !important;
}}
</style>
""", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # Actions after submit
        if del_clicked:
            st.session_state.courses = [c for c in st.session_state.courses if not (c['subject'] == r['subject'] and c['cls'] == r['cls'])]
            st.session_state.data.pop((r['subject'], r['cls']), None)
            st.session_state.favorites.discard(k)
            if rerun: rerun()
        if fav_clicked:
            if fav_on:
                st.session_state.favorites.discard(k)
            else:
                st.session_state.favorites.add(k)
            if rerun: rerun()

        # -------- Info --------
        with col[1]:
            status = "만석" if r['current'] >= r['quota'] else "여석 있음"
            color = "#ff8a80" if r['current'] >= r['quota'] else "#81d4fa"
            st.markdown(f"<div class='course-title'>{r['title']}</div>", unsafe_allow_html=True)
            bar(r['current'], r['quota'], color)
            st.caption(f"상태: {status} | 비율: {r['ratio']*100:.0f}% | 분반: {r['cls']:0>3} | 교수: {r['prof']}")

render()

# after render, handle pending and refresh
if st.session_state.pending:
    subj, cls = st.session_state.pending.pop(0)
    d = fetch(subj, cls, st.session_state.headless)
    st.session_state.data[(subj, cls)] = d
    st.session_state.courses.append({"subject":subj, "cls":cls})
    if rerun: rerun()
elif 'refresh_clicked' in locals() and (refresh_clicked or auto):
    for c in st.session_state.courses:
        k = (c["subject"], c["cls"])
        st.session_state.data[k] = fetch(*k, st.session_state.headless)
    if rerun: rerun()
