import streamlit as st
from PIL import Image   # only if you want to load a local image file

st.set_page_config(
    page_title="수강신청 모니터",          # 탭 제목
    page_icon="/favicon.ico",       # 로컬 경로 / URL / emoji / emoji-shortcode / Material-icon
    layout="wide",
    initial_sidebar_state="collapsed",
)
