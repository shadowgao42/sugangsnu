import os, re, shutil, time, streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DEFAULT_YEAR = 2025
DEFAULT_SEM  = 4
SEM_VALUE = {1: "U000200001U000300001", 2: "U000200001U000300002", 3: "U000200002U000300001", 4: "U000200002U000300002"}
SEM_NAME  = {1: "1학기", 2: "여름학기", 3: "2학기", 4: "겨울학기"}
TITLE_COL, CAP_COL, CURR_COL, PROF_COL, TIME_COL = 6, 13, 14, 11, 8
TIMEOUT = 10
MAX_PAGES_TO_TRY = 20                       

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
DAY_ORDER = "월화수목금토일"
def _format_time_caption(cell_text: str) -> str:
    if not cell_text:
        return ""
    s = cell_text.replace("\xa0", " ")
    s = s.replace("\r", "\n").replace("\u3000", " ").strip()
    pattern = r"([월화수목금토일])\s*[\(（]\s*(\d{1,2})[:：](\d{2})\s*[~∼～\-]\s*(\d{1,2})[:：](\d{2})\s*[\)）]"
    matches = re.findall(pattern, s, flags=re.DOTALL)
    if not matches:
        s2 = " ".join(s.split())
        matches = re.findall(pattern, s2, flags=re.DOTALL)
    if not matches:
        return ""
    groups = {}
    for day, h1, m1, h2, m2 in matches:
        t1 = f"{int(h1):02d}:{m1}"
        t2 = f"{int(h2):02d}:{m2}"
        tm = f"{t1}~{t2}"
        groups.setdefault(tm, []).append(day)
    for tm in list(groups):
        groups[tm] = sorted(set(groups[tm]), key=lambda d: DAY_ORDER.index(d))
    def start_minutes(tm: str) -> int:
        hh, mm = map(int, tm.split("~")[0].split(":"))
        return hh*60 + mm
    items = sorted(groups.items(), key=lambda kv: (min(DAY_ORDER.index(d) for d in kv[1]), start_minutes(kv[0])))
    return " / ".join([f"{'/'.join(days)} ({tm})" for tm, days in items])


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
    rows = drv.find_elements(By.CSS_SELECTOR,"table.tbl_basic tbody tr")
    for i, tr in enumerate(rows):
        tds = tr.find_elements(By.TAG_NAME,"td")
        if not tds:
            continue
        if any(td.text.strip()==cls for td in tds):
            cap = tds[CAP_COL].text if len(tds)>CAP_COL else ""
            m = re.search(r"\((\d+)\)", cap)
            quota = int(m.group(1)) if m else _int(cap)
            current = _int(tds[CURR_COL].text) if len(tds)>CURR_COL else 0
            title = tds[TITLE_COL].text.strip() if len(tds)>TITLE_COL else ""
            prof  = tds[PROF_COL].text.strip() if len(tds)>PROF_COL else ""
            buf = []
            j = i
            while j < len(rows):
                rtds = rows[j].find_elements(By.TAG_NAME,"td")
                ttl  = rtds[TITLE_COL].text.strip() if len(rtds)>TITLE_COL else ""
                if j>i and ttl:
                    break
                if len(rtds)>TIME_COL and rtds[TIME_COL].text.strip():
                    buf.append(rtds[TIME_COL].text.strip())
                else:
                    buf.append(" ".join(td.text for td in rtds if td.text))
                j += 1
            time_caption = _format_time_caption(" ".join(buf))
            return quota,current,title,prof,time_caption
    return None


def _goto_page(drv, page:int):
                                      
    try:
        tbody = WebDriverWait(drv, TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table.tbl_basic tbody")))
        old_html = tbody.get_attribute("innerHTML")
    except Exception:
        old_html = None
                                           
    drv.execute_script("fnGotoPage(arguments[0]);", page)
                 
    WebDriverWait(drv, TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR,"table.tbl_basic tbody tr")))
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

                                             
    for p in range(2, MAX_PAGES_TO_TRY + 1):
        try:
            _goto_page(drv, p)
        except Exception:
                                      
            break
        found = _scan_current_page(drv, cls)
        if found:
            return found
    return None, None, None, None, None

def fetch(subj:str, cls:str, headless:bool):
    drv = driver(headless)
    try:
        open_search(drv, subj)
        quota,current,title,prof,time_caption = read_info(drv, cls)
    except Exception as e:
        return {"subject":subj,"cls":cls,"error":str(e)}
    finally:
        drv.quit()
    if quota is None:
        return {"subject":subj,"cls":cls,"error":"행을 찾지 못했습니다."}
    return {"subject":subj,"cls":cls,"quota":quota,"current":current,"title":title,"prof":prof,"time":time_caption,"ratio":current/quota if quota else 0}

               
                                          
def bar(curr:int, quota:int):
    pct = curr/quota*100 if quota else 0
    color = "#f8b4b4" if curr >= quota else "#a5d8ff"
    st.markdown(
        """
        <div style='display:flex;align-items:center;gap:12px; width:100%; margin-left:4px;'>
            <div style='width:clamp(360px, 48vw, 640px); position:relative; height:24px; background:#eee; border-radius:8px; overflow:hidden; flex:0 0 auto;'>
                <div style='position:absolute; top:0; left:0; bottom:0; width:{pct:.2f}%; background:{color};'></div>
                <div style='position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-weight:600; font-size:13px;'>
                    {curr}/{quota}
                </div>
            </div>
        </div>
        """.format(pct=pct, color=color, curr=curr, quota=quota),
        unsafe_allow_html=True
    )

st.set_page_config(page_title="SNU 수강신청 실시간 모니터", layout="wide")

                                                              
st.markdown(
    """
    <style>
    /* Prevent Streamlit columns from stacking vertically on small screens */
    [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; align-items: center !important; }
    /* Make each column shrink instead of wrapping */
    [data-testid="stHorizontalBlock"] > div { min-width: 0 !important; flex: 0 1 auto !important; }
    /* Tweak Streamlit button to be compact */
    .stButton button { padding: 0.2rem 0.5rem; line-height: 1; }
    </style>
    """,
    unsafe_allow_html=True
)


               
if "courses" not in st.session_state: st.session_state.courses=[]
if "data" not in st.session_state: st.session_state.data={}
if "pending" not in st.session_state: st.session_state.pending=[]
if "headless" not in st.session_state: st.session_state.headless=True

rerun = getattr(st,"rerun",None) or getattr(st,"experimental_rerun",None)
auto_key="__auto_refresh"

st.title(f"SNU 수강신청 실시간 모니터 ({DEFAULT_YEAR}학년도 {SEM_NAME[DEFAULT_SEM]})")

with st.sidebar:
    st.header("설정")
    subj = st.text_input("과목코드", placeholder="예시: 445.206")
    cls  = st.text_input("분반", placeholder="예시: 002")
    add  = st.button("등록", use_container_width=True)

    refresh_clicked = st.button("🔄 수동 새로고침", use_container_width=True)

    auto = st.checkbox("자동 새로고침(과목 등록 시 해제 권장)", False)
    interval = st.slider("새로고침(초)",3,20,5)
    st.session_state.headless = st.checkbox("Headless 모드", st.session_state.headless)
    sort_ratio = st.checkbox("채워진 비율 순 배열", True)

                                  
if add:
    s,c = subj.strip(), cls.strip()
    if not s or not c:
        st.warning("과목코드·분반을 모두 입력하세요.")
    elif any(x["subject"]==s and x["cls"]==c for x in st.session_state.courses) or (s,c) in st.session_state.pending:
        st.info("이미 등록된 과목이거나 로딩 중입니다.")
    else:
        st.session_state.pending.append((s,c))
        (getattr(st,"toast",None) or st.info)(f"{s}-{c} 데이터 로딩 시작")

             
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
        if r is None:
            st.info("데이터 로딩 중...")
            continue
        if "error" in r:
            st.error(f"{r['subject']}-{r['cls']}: {r['error']}")
            continue

                         
        card = st.container()
        with card:
                                          
            hcol = st.columns([0.06, 0.94])
            delete_key = f"del_{r['subject']}_{r['cls']}"
            if hcol[0].button("×", key=delete_key, help="삭제"):
                st.session_state.courses=[c for c in st.session_state.courses if not (c['subject']==r['subject'] and c['cls']==r['cls'])]
                st.session_state.data.pop((r['subject'],r['cls']),None)
                if rerun: rerun()
            with hcol[1]:
                                     
                st.markdown(
                    f"""
                    <div style="display:flex;align-items:center;gap:8px;min-height:32px;">
                        <div style="margin-left:4px; font-weight:700; font-size:15px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                            {r['title']}
                        </div>
                        {f'<span style="font-size:12px;color:#6b7280;white-space:nowrap;">{r["time"]}</span>' if r.get('time') else ''}
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                        
                bar(r['current'], r['quota'])

                       
                status = "만석" if r['current']>=r['quota'] else "여석있음"
                st.caption(f"{status} | 비율: {r['ratio']*100:.0f}% | 분반: {r['cls']:0>3} | 교수: {r['prof']}")

render()

                                          
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
                  
    for c in st.session_state.courses:
        k=(c["subject"],c["cls"])
        st.session_state.data[k] = fetch(*k, st.session_state.headless)
    if rerun: rerun()
