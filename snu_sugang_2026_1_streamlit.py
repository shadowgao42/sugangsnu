# snu_sugang_2026_1_streamlit.py
# Streamlit app: SNU (서울대학교) 2026-1 수강신청 강좌 검색/필터
#
# Run:
#   pip install streamlit requests pandas openpyxl xlrd==2.0.1
#   streamlit run snu_sugang_2026_1_streamlit.py
#
# Notes:
# - The SNU endpoint returns an Excel file. Some environments may require xlrd to read legacy .xls.
# - If .xls parsing fails, this app attempts fallback parsing.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from urllib.parse import parse_qsl


# -----------------------------
# Configuration
# -----------------------------
URL = "https://sugang.snu.ac.kr/sugang/cc/cc100InterfaceExcel.action"

# Default payload copied from user's console (2026, 1st semester)
PAYLOAD_STR_DEFAULT = (
    "workType=EX&pageNo=1&srchOpenSchyy=2026&"
    "srchOpenShtm=U000200001U000300001&"
    "srchSbjtNm=&srchSbjtCd=&seeMore=&srchCptnCorsFg=&srchOpenShyr=&"
    "srchOpenUpSbjtFldCd=&srchOpenSbjtFldCd=&srchOpenUpDeptCd=&srchOpenDeptCd=&"
    "srchOpenMjCd=&srchOpenSubmattCorsFg=&srchOpenSubmattFgCd1=&srchOpenSubmattFgCd2=&"
    "srchOpenSubmattFgCd3=&srchOpenSubmattFgCd4=&srchOpenSubmattFgCd5=&srchOpenSubmattFgCd6=&"
    "srchOpenSubmattFgCd7=&srchOpenSubmattFgCd8=&srchOpenSubmattFgCd9=&srchExcept=&"
    "srchOpenPntMin=&srchOpenPntMax=&srchCamp=&srchBdNo=&srchProfNm=&"
    "srchOpenSbjtTmNm=&srchOpenSbjtDayNm=&srchOpenSbjtTm=&srchOpenSbjtNm=&"
    "srchTlsnAplyCapaCntMin=&srchTlsnAplyCapaCntMax=&srchLsnProgType=&"
    "srchTlsnRcntMin=&srchTlsnRcntMax=&srchMrksGvMthd=&srchIsEngSbjt=&"
    "srchMrksApprMthdChgPosbYn=&srchIsPendingCourse=&srchGenrlRemoteLtYn=&"
    "srchLanguage=ko&srchCurrPage=1&srchPageSize=9999"
)

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Streamlit; sugang data fetcher)",
}

KST = timezone(timedelta(hours=9))


# -----------------------------
# Helpers
# -----------------------------
def payload_str_to_dict(payload_str: str) -> Dict[str, str]:
    """
    Convert application/x-www-form-urlencoded string into a flat dict.
    """
    pairs = list(parse_qsl(payload_str, keep_blank_values=True))
    return {k: v for k, v in pairs}


def find_col(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    """
    Find first matching column name (exact match) among candidates.
    """
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def safe_int(x) -> Optional[int]:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = re.sub(r"[^\d\-]+", "", s)
    if s in {"", "-"}:
        return None
    try:
        return int(s)
    except Exception:
        return None


def safe_float(x) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = re.sub(r"[^\d\.\-]+", "", s)
    if s in {"", "-", ".", "-."}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def contains_any(text: str, needles: Iterable[str]) -> bool:
    t = str(text)
    return any(n in t for n in needles)


def parse_time_ranges(schedule_text: str) -> List[Tuple[int, int]]:
    """
    Extract time ranges from a schedule string.
    Returns list of (start_minute, end_minute) in minutes from 00:00.
    Heuristic: find patterns like 09:00-10:15 or 9:00~10:15.
    """
    s = str(schedule_text)
    # Normalize separators
    s = s.replace("~", "-").replace("–", "-").replace("—", "-")
    pat = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
    out: List[Tuple[int, int]] = []
    for m in pat.finditer(s):
        h1, m1, h2, m2 = map(int, m.groups())
        start = h1 * 60 + m1
        end = h2 * 60 + m2
        if 0 <= start < 24 * 60 and 0 <= end <= 24 * 60 and end > start:
            out.append((start, end))
    return out


def schedule_overlaps(schedule_text: str, window_start: int, window_end: int) -> bool:
    """
    True if any time range in schedule_text overlaps [window_start, window_end].
    """
    ranges = parse_time_ranges(schedule_text)
    if not ranges:
        return False
    for s, e in ranges:
        if not (e < window_start or s > window_end):
            return True
    return False


@dataclass
class ColumnMap:
    course_name: Optional[str]
    course_code: Optional[str]
    class_no: Optional[str]
    dept: Optional[str]
    major: Optional[str]
    professor: Optional[str]
    credits: Optional[str]
    language: Optional[str]
    campus: Optional[str]
    schedule: Optional[str]
    capacity: Optional[str]
    enrolled: Optional[str]
    remaining: Optional[str]


def guess_columns(df: pd.DataFrame) -> ColumnMap:
    """
    Guess common SNU course columns across Korean/English labels.
    This is intentionally permissive. If the Excel format changes, the app still runs.
    """
    return ColumnMap(
        course_name=find_col(df, ["교과목명", "과목명", "강좌명", "Subject", "Course Name", "교과목 명"]),
        course_code=find_col(df, ["교과목번호", "교과목번호(학수번호)", "학수번호", "Subject Code", "Course Code", "교과목 번호"]),
        class_no=find_col(df, ["강좌번호", "강좌 번호", "분반", "분반번호", "Class No", "Section"]),
        dept=find_col(df, ["개설학과", "개설학부", "개설부서", "학과", "Department", "개설학과(부)"]),
        major=find_col(df, ["전공", "전공명", "Major"]),
        professor=find_col(df, ["담당교수", "교수명", "교수", "Professor", "Instructor"]),
        credits=find_col(df, ["학점", "학점수", "Credits"]),
        language=find_col(df, ["강의언어", "언어", "Language"]),
        campus=find_col(df, ["캠퍼스", "Campus"]),
        schedule=find_col(df, ["강의시간", "수업시간", "강의시간/강의실", "강의시간/강의실(비대면 포함)", "Time", "Schedule"]),
        capacity=find_col(df, ["정원", "수강정원", "수강정원(정원)", "Capacity"]),
        enrolled=find_col(df, ["신청인원", "수강신청인원", "수강인원", "Enrolled", "Applied"]),
        remaining=find_col(df, ["잔여", "잔여석", "여석", "Remaining", "Seats Left"]),
    )


def parse_excel_bytes(content: bytes) -> pd.DataFrame:
    """
    Parse bytes returned from the endpoint into a DataFrame.
    Tries multiple engines and fallbacks.
    """
    bio = BytesIO(content)

    # 1) Try xls (xlrd)
    try:
        return normalize_columns(pd.read_excel(bio, dtype=str, engine="xlrd"))
    except Exception:
        pass

    # Reset buffer
    bio = BytesIO(content)

    # 2) Try xlsx (openpyxl)
    try:
        return normalize_columns(pd.read_excel(bio, dtype=str, engine="openpyxl"))
    except Exception:
        pass

    # 3) Try reading as HTML table (some "excel" downloads are actually HTML)
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            text = content.decode(enc, errors="ignore")
            tables = pd.read_html(text)
            if tables:
                return normalize_columns(tables[0].astype(str))
        except Exception:
            continue

    raise RuntimeError("Failed to parse the downloaded file as Excel/HTML. Install xlrd for .xls parsing, or verify the endpoint response.")


@st.cache_data(ttl=60 * 10, show_spinner=False)
def fetch_courses(payload_str: str) -> Tuple[pd.DataFrame, str]:
    """
    Fetch Excel from SNU and parse into a DataFrame.
    Returns (df, fetched_at_iso_kst).
    """
    payload = payload_str_to_dict(payload_str)

    resp = requests.post(URL, headers=HEADERS, data=payload, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    df = parse_excel_bytes(resp.content)

    fetched_at = datetime.now(tz=KST).isoformat(timespec="seconds")
    return df, fetched_at


def apply_filters(
    df: pd.DataFrame,
    cm: ColumnMap,
    keyword: str,
    dept_sel: List[str],
    prof_sel: List[str],
    campus_sel: List[str],
    lang_only_eng: bool,
    credits_range: Optional[Tuple[float, float]],
    seats_only: bool,
    day_tokens: List[str],
    time_window: Optional[Tuple[int, int]],
) -> pd.DataFrame:
    out = df.copy()

    # Keyword search across common text columns
    keyword = (keyword or "").strip()
    if keyword:
        cols_for_search = [c for c in [cm.course_name, cm.course_code, cm.class_no, cm.dept, cm.professor, cm.schedule] if c]
        if cols_for_search:
            mask = False
            for c in cols_for_search:
                mask = mask | out[c].astype(str).str.contains(re.escape(keyword), case=False, na=False)
            out = out[mask]

    # Department filter
    if cm.dept and dept_sel:
        out = out[out[cm.dept].astype(str).isin(dept_sel)]

    # Professor filter
    if cm.professor and prof_sel:
        out = out[out[cm.professor].astype(str).isin(prof_sel)]

    # Campus filter
    if cm.campus and campus_sel:
        out = out[out[cm.campus].astype(str).isin(campus_sel)]

    # English-only filter
    if cm.language and lang_only_eng:
        # Heuristic: include rows that mention English/영어/ENG
        out = out[out[cm.language].astype(str).apply(lambda s: contains_any(s, ["영어", "English", "ENG"]))]

    # Credits filter
    if cm.credits and credits_range is not None:
        lo, hi = credits_range
        credits_num = out[cm.credits].apply(safe_float)
        out = out[(credits_num >= lo) & (credits_num <= hi)]

    # Seats available filter
    if seats_only:
        # Prefer explicit remaining column; else compute from capacity/enrolled if available
        if cm.remaining:
            rem = out[cm.remaining].apply(safe_int)
            out = out[(rem.fillna(0) > 0)]
        elif cm.capacity and cm.enrolled:
            cap = out[cm.capacity].apply(safe_int)
            enr = out[cm.enrolled].apply(safe_int)
            rem = (cap.fillna(0) - enr.fillna(0))
            out = out[(rem > 0)]

    # Day filter (search inside schedule text)
    if cm.schedule and day_tokens:
        out = out[out[cm.schedule].astype(str).apply(lambda s: any(tok in s for tok in day_tokens))]

    # Time window filter (overlap check)
    if cm.schedule and time_window is not None:
        w0, w1 = time_window
        out = out[out[cm.schedule].astype(str).apply(lambda s: schedule_overlaps(s, w0, w1))]

    return out


def enrich_seat_metrics(df: pd.DataFrame, cm: ColumnMap) -> pd.DataFrame:
    """
    Add computed columns for remaining seats and competition ratio when possible.
    """
    out = df.copy()

    cap_col = cm.capacity
    enr_col = cm.enrolled
    rem_col = cm.remaining

    # Remaining seats
    if "잔여석(계산)" not in out.columns:
        if rem_col:
            out["잔여석(계산)"] = out[rem_col].apply(safe_int)
        elif cap_col and enr_col:
            cap = out[cap_col].apply(safe_int)
            enr = out[enr_col].apply(safe_int)
            out["잔여석(계산)"] = (cap.fillna(0) - enr.fillna(0)).astype(int)
        else:
            out["잔여석(계산)"] = None

    # Competition ratio
    if "경쟁률(계산)" not in out.columns:
        if cap_col and enr_col:
            cap = out[cap_col].apply(safe_float)
            enr = out[enr_col].apply(safe_float)
            ratio = enr / cap
            out["경쟁률(계산)"] = ratio.replace([float("inf"), -float("inf")], pd.NA)
        else:
            out["경쟁률(계산)"] = None

    return out


def to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="courses")
    return bio.getvalue()


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="SNU 2026-1 Course Search", layout="wide")

st.title("SNU 2026-1 Course Search (2026학년도 1학기)")
st.caption("Data source: sugang.snu.ac.kr (Excel interface). Use filters to narrow down courses. "
           "If the endpoint format changes, adjust column mappings or parsing fallback accordingly.")

with st.sidebar:
    st.header("Fetch settings")

    use_server_side_query = st.checkbox("Use server-side query (faster, optional)", value=False)

    keyword_server = st.text_input("Server-side subject keyword (optional)", value="", help="Sets srchSbjtNm / srchOpenSbjtNm if enabled.")
    course_code_server = st.text_input("Server-side course code (optional)", value="", help="Sets srchSbjtCd if enabled.")

    page_size = st.number_input("Page size", min_value=100, max_value=20000, value=9999, step=100)

    st.divider()
    st.header("Filters")

    keyword = st.text_input("Keyword (local filter)", value="", help="Searches across course name/code/department/professor/schedule.")

    seats_only = st.checkbox("Show only courses with seats available", value=False)
    lang_only_eng = st.checkbox("English-taught only (heuristic)", value=False)

    credits_on = st.checkbox("Filter by credits", value=False)
    credits_range = None
    if credits_on:
        credits_range = st.slider("Credits range", min_value=0.0, max_value=10.0, value=(0.0, 6.0), step=0.5)

    day_tokens = st.multiselect("Days (local, based on schedule text)", ["월", "화", "수", "목", "금", "토", "일"], default=[])

    time_on = st.checkbox("Filter by time window (overlap; heuristic)", value=False)
    time_window = None
    if time_on:
        # minutes from 00:00
        w0, w1 = st.slider("Time window (KST)", min_value=0, max_value=24 * 60, value=(9 * 60, 18 * 60), step=15)
        time_window = (int(w0), int(w1))

    sort_by = st.selectbox(
        "Sort",
        options=["교과목명", "경쟁률(계산)", "잔여석(계산)", "학점", "학수번호/교과목번호"],
        index=0
    )

    st.divider()
    refresh = st.button("Refresh data now", type="primary")


# Build payload
payload = payload_str_to_dict(PAYLOAD_STR_DEFAULT)
payload["srchPageSize"] = str(int(page_size))
payload["srchCurrPage"] = "1"
payload["pageNo"] = "1"
payload["srchLanguage"] = "ko"

if use_server_side_query:
    if keyword_server.strip():
        payload["srchSbjtNm"] = keyword_server.strip()
        payload["srchOpenSbjtNm"] = keyword_server.strip()
    else:
        payload["srchSbjtNm"] = ""
        payload["srchOpenSbjtNm"] = ""

    if course_code_server.strip():
        payload["srchSbjtCd"] = course_code_server.strip()
    else:
        payload["srchSbjtCd"] = ""
else:
    # Keep empty to fetch all
    payload["srchSbjtNm"] = ""
    payload["srchOpenSbjtNm"] = ""
    payload["srchSbjtCd"] = ""


payload_str = "&".join([f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in payload.items()])

# Refresh caching by changing key
if refresh:
    # Clear cache for fresh fetch
    fetch_courses.clear()

with st.spinner("Fetching course list..."):
    try:
        raw_df, fetched_at = fetch_courses(payload_str)
    except Exception as e:
        st.error("Failed to fetch/parse course data.")
        st.exception(e)
        st.stop()

raw_df = normalize_columns(raw_df)
cm = guess_columns(raw_df)

# Build dynamic selectable filters based on present columns
with st.sidebar:
    # Dynamic multiselect filters from data
    if cm.dept:
        dept_values = sorted([x for x in raw_df[cm.dept].dropna().astype(str).unique() if x.strip() and x.lower() != "nan"])
        dept_sel = st.multiselect("Department", dept_values, default=[])
    else:
        dept_sel = []

    if cm.professor:
        prof_values = sorted([x for x in raw_df[cm.professor].dropna().astype(str).unique() if x.strip() and x.lower() != "nan"])
        prof_sel = st.multiselect("Professor", prof_values, default=[])
    else:
        prof_sel = []

    if cm.campus:
        campus_values = sorted([x for x in raw_df[cm.campus].dropna().astype(str).unique() if x.strip() and x.lower() != "nan"])
        campus_sel = st.multiselect("Campus", campus_values, default=[])
    else:
        campus_sel = []


filtered = apply_filters(
    raw_df,
    cm=cm,
    keyword=keyword,
    dept_sel=dept_sel,
    prof_sel=prof_sel,
    campus_sel=campus_sel,
    lang_only_eng=lang_only_eng,
    credits_range=credits_range if credits_on else None,
    seats_only=seats_only,
    day_tokens=day_tokens,
    time_window=time_window,
)

filtered = enrich_seat_metrics(filtered, cm)

# Sorting
def sort_key(df: pd.DataFrame) -> pd.DataFrame:
    if sort_by == "교과목명":
        if cm.course_name:
            return df.sort_values(by=[cm.course_name], kind="mergesort")
        return df
    if sort_by == "경쟁률(계산)":
        if "경쟁률(계산)" in df.columns:
            return df.sort_values(by=["경쟁률(계산)"], ascending=False, kind="mergesort")
        return df
    if sort_by == "잔여석(계산)":
        if "잔여석(계산)" in df.columns:
            return df.sort_values(by=["잔여석(계산)"], ascending=False, kind="mergesort")
        return df
    if sort_by == "학점":
        if cm.credits:
            temp = df.copy()
            temp["_credits_num"] = temp[cm.credits].apply(safe_float)
            temp = temp.sort_values(by=["_credits_num"], ascending=False, kind="mergesort").drop(columns=["_credits_num"])
            return temp
        return df
    if sort_by == "학수번호/교과목번호":
        if cm.course_code:
            return df.sort_values(by=[cm.course_code], kind="mergesort")
        return df
    return df

filtered = sort_key(filtered)

# Summary
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total courses (fetched)", f"{len(raw_df):,}")
c2.metric("Filtered courses", f"{len(filtered):,}")
c3.metric("Fetched at (KST)", fetched_at)
c4.metric("Columns detected", f"{len(raw_df.columns)}")

st.subheader("Detected columns (auto)")
detected = {
    "course_name": cm.course_name,
    "course_code": cm.course_code,
    "class_no": cm.class_no,
    "dept": cm.dept,
    "major": cm.major,
    "professor": cm.professor,
    "credits": cm.credits,
    "language": cm.language,
    "campus": cm.campus,
    "schedule": cm.schedule,
    "capacity": cm.capacity,
    "enrolled": cm.enrolled,
    "remaining": cm.remaining,
}
st.json({k: v for k, v in detected.items()})

st.subheader("Courses")
st.dataframe(
    filtered,
    use_container_width=True,
    hide_index=True,
)

st.subheader("Download filtered data")
colA, colB = st.columns(2)

with colA:
    csv_bytes = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download CSV (UTF-8-SIG)",
        data=csv_bytes,
        file_name="snu_2026_1_courses_filtered.csv",
        mime="text/csv",
        use_container_width=True,
    )

with colB:
    try:
        xlsx_bytes = to_xlsx_bytes(filtered)
        st.download_button(
            "Download Excel (.xlsx)",
            data=xlsx_bytes,
            file_name="snu_2026_1_courses_filtered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as e:
        st.warning("Excel export failed (openpyxl may be missing). CSV download should still work.")
        st.caption(str(e))


st.divider()
with st.expander("Troubleshooting / Notes"):
    st.markdown(
        """
- If you see **parsing errors**, install `xlrd==2.0.1` for legacy `.xls` parsing:
  - `pip install xlrd==2.0.1`
- If the file is actually `.xlsx`, ensure `openpyxl` is installed:
  - `pip install openpyxl`
- The **day/time filters** are **heuristics** that search within the schedule text and parse time ranges like `09:00-10:15`.
- If the Excel column headers change, the app will still run; but filters may be limited until you adjust the `guess_columns()` candidates.
        """
    )
