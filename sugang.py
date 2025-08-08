import os, re, shutil, streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DEFAULT_YEAR=2025
DEFAULT_SEM=3
SEM_VALUE={1:"U000200001U000300001",2:"U000200001U000300002",3:"U000200002U000300001",4:"U000200002U000300002"}
SEM_NAME={1:"1학기",2:"여름학기",3:"2학기",4:"겨울학기"}
TITLE_COL,CAP_COL,CURR_COL,PROF_COL=6,13,14,11
TIMEOUT=10
CHROMEDRIVER=["/usr/bin/chromedriver","/usr/local/bin/chromedriver","/usr/lib/chromium/chromedriver",shutil.which("chromedriver")]

def driver(headless=True):
    path=next((p for p in CHROMEDRIVER if p and os.path.exists(p)),None)
    if not path: raise RuntimeError("chromedriver not found")
    opt=webdriver.ChromeOptions()
    if headless: opt.add_argument("--headless=new")
    opt.add_argument("--no-sandbox")
    opt.add_argument("--disable-dev-shm-usage")
    opt.add_argument("--window-size=1600,1000")
    return webdriver.Chrome(service=Service(path),options=opt)

def _int(x):
    m=re.search(r"\d+",x.replace(",",""))
    return int(m.group()) if m else 0

def open_search(drv,subject):
    drv.get("https://shine.snu.ac.kr/uni/sugang/cc/cc100.action")
    WebDriverWait(drv,TIMEOUT).until(EC.presence_of_element_located((By.ID,"srchOpenSchyy")))
    drv.execute_script("""document.getElementById('srchOpenSchyy').value=arguments[0];document.getElementById('srchOpenShtm').value=arguments[1];document.getElementById('srchSbjtCd').value=arguments[2];fnInquiry();""",str(DEFAULT_YEAR),SEM_VALUE[DEFAULT_SEM],subject.strip())

def read_info(drv,cls):
    WebDriverWait(drv,TIMEOUT).until(EC.presence_of_element_located((By.CSS_SELECTOR,"table.tbl_basic tbody tr")))
    for tr in drv.find_elements(By.CSS_SELECTOR,"table.tbl_basic tbody tr"):
        tds=tr.find_elements(By.TAG_NAME,"td")
        if len(tds)<=CURR_COL: continue
        if any(td.text.strip()==cls for td in tds):
            cap=tds[CAP_COL].text
            m=re.search(r"\((\d+)\)",cap)
            quota=int(m.group(1)) if m else _int(cap)
            current=_int(tds[CURR_COL].text)
            title=tds[TITLE_COL].text.strip()
            prof=tds[PROF_COL].text.strip()
            return quota,current,title,prof
    return None,None,None,None

def fetch(subject,cls,headless):
    drv=driver(headless)
    try:
        open_search(drv,subject)
        quota,current,title,prof=read_info(drv,cls)
    except Exception as e:
        return {"subject":subject,"cls":cls,"error":str(e)}
    finally:
        drv.quit()
    if quota is None:
        return {"subject":subject,"cls":cls,"error":"행을 찾지 못했습니다."}
    return {"subject":subject,"cls":cls,"quota":quota,"current":current,"title":title,"prof":prof,"ratio":current/quota if quota else 0}

def bar(title,current,quota):
    pct=current/quota*100 if quota else 0
    color="#e53935" if current>=quota else "#1e88e5"
    st.markdown(f"<div style='display:flex;align-items:center;gap:12px'><div style='flex:1;position:relative;height:24px;background:#eee;border-radius:8px;overflow:hidden'><div style='position:absolute;top:0;left:0;bottom:0;width:{pct:.2f}%;background:{color}'></div></div><span style='font-weight:600;white-space:nowrap'>{title} ({current}/{quota})</span></div>",unsafe_allow_html=True)

st.set_page_config(page_title="SNU 수강신청 실시간 모니터",layout="wide")
if "courses" not in st.session_state: st.session_state.courses=[]
if "data" not in st.session_state: st.session_state.data={}

auto_key="__auto_refresh"

auto_default=True

st.title("SNU 수강신청 실시간 모니터")
with st.sidebar:
    subj=st.text_input("과목코드",placeholder="445.206")
    cls=st.text_input("분반",placeholder="002")
    add=st.button("등록",use_container_width=True)
    auto=st.checkbox("자동 새로고침",auto_default)
    interval=st.slider("새로고침(초)",1,10,2)
    headless=st.checkbox("Headless 모드",True)
    sort_ratio=st.checkbox("경쟁률 순 배열",True)

if add:
    s=subj.strip(); c=cls.strip()
    if not s or not c:
        st.warning("과목코드·분반을 모두 입력하세요.")
    elif any(x["subject"]==s and x["cls"]==c for x in st.session_state.courses):
        st.info("이미 등록된 과목입니다.")
    else:
        with st.spinner("과목 정보를 불러오는 중..."):
            d=fetch(s,c,headless)
        if "error" in d and "행을 찾지 못했습니다" in d["error"]:
            t=getattr(st,"toast",None)
            (t or st.warning)("과목 정보를 찾지 못했습니다.")
        elif "error" in d:
            st.error(f"{s}-{c}: {d['error']}")
        else:
            st.session_state.courses.append({"subject":s,"cls":c})
            st.session_state.data[(s,c)]=d
            st.success(f"{s}-{c} 등록 완료")

ar=getattr(st,"autorefresh",None) or getattr(st,"st_autorefresh",None)
if auto and ar:
    ar(interval=interval*1000,key=auto_key)

rerun=getattr(st,"rerun",None) or getattr(st,"experimental_rerun",None)

def render():
    if not st.session_state.courses:
        st.info("사이드바에서 과목을 등록하세요.")
        return
    res=[]
    if auto:
        with st.spinner("과목 정보 갱신 중..."):
            for c in st.session_state.courses:
                k=(c["subject"],c["cls"])
                st.session_state.data[k]=fetch(*k,headless)
                res.append(st.session_state.data[k])
    else:
        for c in st.session_state.courses:
            k=(c["subject"],c["cls"])
            if k not in st.session_state.data:
                st.session_state.data[k]=fetch(*k,headless)
            res.append(st.session_state.data[k])
    if sort_ratio:
        res.sort(key=lambda x:x.get("ratio",0),reverse=True)
    st.subheader(f"{DEFAULT_YEAR}-{SEM_NAME[DEFAULT_SEM]}")
    for r in res:
        col=st.columns([1,9])
        if col[0].button("×",key=f"del_{r['subject']}_{r['cls']}"):
            st.session_state.courses=[c for c in st.session_state.courses if not (c['subject']==r['subject'] and c['cls']==r['cls'])]
            st.session_state.data.pop((r['subject'],r['cls']),None)
            (rerun or st.stop)()
        with col[1]:
            if "error" in r:
                st.error(f"{r['subject']}-{r['cls']}: {r['error']}")
            else:
                bar(r['title'],r['current'],r['quota'])
                status="만석" if r['current']>=r['quota'] else "여석 있음"
                st.caption(f"상태: {status} | 비율: {r['ratio']*100:.0f}% | 분반: {r['cls']:0>3} | 교수: {r['prof']}")

render()
