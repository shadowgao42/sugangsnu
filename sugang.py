
import os, re, shutil, streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DEFAULT_YEAR = 2025
DEFAULT_SEM  = 3
SEM_VALUE = {1: "U000200001U000300001", 2: "U000200001U000300002", 3: "U000200002U000300001", 4: "U000200002U000300002"}
SEM_NAME  = {1: "1학기", 2: "여름학기", 3: "2학기", 4: "겨울학기"}
TITLE_COL, CAP_COL, CURR_COL, PROF_COL = 6, 13, 14, 11
TIMEOUT = 10

CHROMEDRIVER = [
    "/usr/bin/chromedriver",
    "/usr/local/bin/chromedriver",
    "/usr/lib/chromium/chromedriver",
    shutil.which("chromedriver"),
]

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

def read_info(drv, cls:str):
    WebDriverWait(drv,TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR,"table.tbl_basic tbody tr")))
    for tr in drv.find_elements(By.CSS_SELECTOR,"table.tbl_basic tbody tr"):
        tds = tr.find_elements(By.TAG_NAME,"td")
        if len(tds)<=CURR_COL: continue
        if any(td.text.strip()==cls for td in tds):
            cap = tds[CAP_COL].text
            m = re.search(r"\((\d+)\)", cap)
            quota = int(m.group(1)) if m else _int(cap)
            current = _int(tds[CURR_COL].text)
            title = tds[TITLE_COL].text.strip()
            prof  = tds[PROF_COL].text.strip()
            return quota,current,title,prof
    return None,None,None,None

def fetch(subj:str, cls:str, headless:bool):
    drv = driver(headless)
    try:
        open_search(drv, subj)
        quota,current,title,prof = read_info(drv, cls)
    except Exception as e:
        return {"subject":subj,"cls":cls,"error":str(e)}
    finally:
        drv.quit()
    if quota is None:
        return {"subject":subj,"cls":cls,"error":"행을 찾지 못했습니다."}
    return {"subject":subj,"cls":cls,"quota":quota,"current":current,"title":title,"prof":prof,"ratio":current/quota if quota else 0}

def bar(t:str,curr:int,quota:int):
    pct = curr/quota*100 if quota else 0
    color = "#e53935" if curr>=quota else "#1e88e5"
    st.markdown(
        "<div style='display:flex;align-items:center;gap:12px'>"
        "<div style='flex:1;position:relative;height:24px;background:#eee;border-radius:8px;overflow:hidden'>"
        f"<div style='position:absolute;top:0;left:0;bottom:0;width:{pct:.2f}%;background:{color}'></div>"
        "</div><span style='font-weight:600;white-space:nowrap'>"
        f"{t} ({curr}/{quota})</span></div>",
        unsafe_allow_html=True
    )

st.set_page_config(page_title="SNU 수강신청 실시간 모니터", layout="wide")

# session state
if "courses" not in st.session_state: st.session_state.courses=[]
if "data" not in st.session_state: st.session_state.data={}
if "pending" not in st.session_state: st.session_state.pending=[]
if "headless" not in st.session_state: st.session_state.headless=True

rerun = getattr(st,"rerun",None) or getattr(st,"experimental_rerun",None)
auto_key="__auto_refresh"

st.title(f"SNU 수강신청 실시간 모니터 ({DEFAULT_YEAR}학년도 {SEM_NAME[DEFAULT_SEM]})")

with st.sidebar:
    st.header("설정")
    subj = st.text_input("과목코드", placeholder="445.206")
    cls  = st.text_input("분반", placeholder="002")
    add  = st.button("등록", use_container_width=True)

    refresh_clicked = st.button("🔄 수동 새로고침", use_container_width=True)

    auto = st.checkbox("자동 새로고침(과목 등록 시 해제 권장)", False)
    interval = st.slider("새로고침(초)",1,10,2)
    st.session_state.headless = st.checkbox("Headless 모드", st.session_state.headless)
    sort_ratio = st.checkbox("경쟁률 순 배열", True)

# queue fetch rather than blocking
if add:
    s,c = subj.strip(), cls.strip()
    if not s or not c:
        st.warning("과목코드·분반을 모두 입력하세요.")
    elif any(x["subject"]==s and x["cls"]==c for x in st.session_state.courses) or (s,c) in st.session_state.pending:
        st.info("이미 등록된 과목이거나 로딩 중입니다.")
    else:
        st.session_state.pending.append((s,c))
        (getattr(st,"toast",None) or st.info)(f"{s}-{c} 데이터 로딩 시작")

# autorefresh
ar = getattr(st,"autorefresh",None) or getattr(st,"st_autorefresh",None)
if auto and ar:
    ar(interval=interval*1000, key=auto_key)

def render():
    if not st.session_state.courses:
        st.info("사이드바에서 과목을 등록하세요.")
        return
    res = []
    for c in st.session_state.courses:
        k=(c["subject"],c["cls"])
        res.append(st.session_state.data.get(k))
    if sort_ratio:
        res.sort(key=lambda x:x.get("ratio",0) if x else 0, reverse=True)
    for r in res:
        col = st.columns([1,9])
        if col[0].button("×", key=f"del_{r['subject']}_{r['cls']}"):
            st.session_state.courses=[c for c in st.session_state.courses if not (c['subject']==r['subject'] and c['cls']==r['cls'])]
            st.session_state.data.pop((r['subject'],r['cls']),None)
            if rerun: rerun()
        with col[1]:
            if r is None:
                st.info("데이터 로딩 중...")
            elif "error" in r:
                st.error(f"{r['subject']}-{r['cls']}: {r['error']}")
            else:
                bar(r['title'],r['current'],r['quota'])
                status = "만석" if r['current']>=r['quota'] else "여석 있음"
                st.caption(f"상태: {status} | 비율: {r['ratio']*100:.0f}% | 분반: {r['cls']:0>3} | 교수: {r['prof']}")

render()

# after render, handle pending and refresh
if st.session_state.pending:
    subj,cls = st.session_state.pending.pop(0)
    d = fetch(subj,cls,st.session_state.headless)
    if "error" in d and "행을 찾지 못했습니다" in d["error"]:
        (getattr(st,"toast",None) or st.warning)(f"{subj}-{cls} 과목 정보를 찾지 못했습니다.")
    elif "error" in d:
        st.session_state.data[(subj,cls)] = d
        st.session_state.courses.append({"subject":subj,"cls":cls})
    else:
        st.session_state.data[(subj,cls)] = d
        st.session_state.courses.append({"subject":subj,"cls":cls})
    if rerun: rerun()
elif refresh_clicked or auto:
    # full refresh
    for c in st.session_state.courses:
        k=(c["subject"],c["cls"])
        st.session_state.data[k] = fetch(*k, st.session_state.headless)
    if rerun: rerun()
