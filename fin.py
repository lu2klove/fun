import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests
import re

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V1.4",
    page_icon="📈",
    layout="wide"
)

# --- 2. Firestore 데이터베이스 초기화 (에러 핸들링 강화) ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            if "text_key" in st.secrets["firebase"]:
                raw_json = st.secrets["firebase"]["text_key"]
                
                # JSON 내의 제어 문자 및 줄바꿈 처리 강화
                # 특히 private_key의 \n 문자가 실제 줄바꿈으로 인식되도록 처리
                clean_json = raw_json.replace('\n', '\\n').replace('\r', '\\r')
                # 이미 이스케이프 된 경우 중복 방지
                clean_json = clean_json.replace('\\\\n', '\\n')
                
                try:
                    key_dict = json.loads(raw_json, strict=False)
                except:
                    # strict=False로도 실패할 경우 정규식으로 제어 문자 제거 시도
                    fixed_json = re.sub(r'[\x00-\x1F\x7F]', '', raw_json)
                    key_dict = json.loads(fixed_json)
                
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                
                creds = service_account.Credentials.from_service_account_info(key_dict)
                client = firestore.Client(credentials=creds, project=key_dict.get('project_id'))
                return client
        return None
    except Exception as e:
        st.error(f"⚠️ DB 연결 인증 오류: {e}")
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. 데이터 수집 함수 (한국 종목 대응 강화) ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        if not ticker: return 0.0, 0.0, 0.0
        yt = yf.Ticker(ticker)
        data = yt.history(period="5d")
        if not data.empty:
            price = data['Close'].iloc[-1]
            if len(data) >= 2:
                prev_price = data['Close'].iloc[-2]
                change = price - prev_price
                change_pct = (change / prev_price) * 100
            else:
                change, change_pct = 0.0, 0.0
            return float(price), float(change), float(change_pct)
    except:
        pass
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=3600)
def get_info_data(ticker):
    """국내 종목(삼성전자 등)의 데이터 누락 문제를 해결하기 위한 백업 로직"""
    try:
        if not ticker: return None
        yt = yf.Ticker(ticker)
        info = yt.info
        
        # 데이터가 아예 비어있는 경우를 대비한 기본값 처리
        if not info or len(info) < 5:
            # info가 부실할 경우 fast_info나 다른 경로로 최소한의 데이터 구성
            return {
                "marketCap": 0,
                "forwardPE": 0,
                "trailingPE": 0,
                "priceToBook": 0,
                "dividendYield": 0,
                "returnOnEquity": 0,
                "longBusinessSummary": f"{ticker} 종목의 상세 정보가 Yahoo Finance에 등록되어 있지 않습니다. (국내 종목은 제한적일 수 있습니다.)"
            }

        return {
            "marketCap": info.get('marketCap') or info.get('totalAssets') or 0,
            "forwardPE": info.get('forwardPE') or info.get('trailingPE') or 0,
            "trailingPE": info.get('trailingPE') or 0,
            "priceToBook": info.get('priceToBook') or 0,
            "dividendYield": info.get('dividendYield') or 0,
            "returnOnEquity": info.get('returnOnEquity') or 0,
            "longBusinessSummary": info.get('longBusinessSummary') or info.get('shortName') or '정보를 불러올 수 없습니다.'
        }
    except:
        return None

# --- 4. 티커 검색 로직 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA",
    "엔비디아": "NVDA"
}

def search_ticker(query):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = res.json()
        if data.get('quotes'): return data['quotes'][0]['symbol']
    except: pass
    return None

def get_ticker_from_name(name):
    clean = name.strip()
    if clean in COMPANY_TICKER_MAP: return COMPANY_TICKER_MAP[clean]
    if clean.replace(".","").isalnum() and clean.upper() == clean: return clean
    found = search_ticker(clean)
    return found if found else clean.upper()

# --- 5. 메인 UI ---
st.title("📊 글로벌 경제 통합 대시보드")

# API 비활성화 및 인증 에러 가이드
if db is None:
    st.warning("⚠️ Firestore 인증에 실패했습니다. 'secrets.toml'의 JSON 형식을 다시 확인하세요.")
else:
    try:
        db.collection(COLLECTION_NAME).limit(1).get()
    except Exception as e:
        if "403" in str(e) or "disabled" in str(e).lower():
            st.error("🚨 **중요: Firestore API를 활성화해야 합니다.**")
            st.markdown(f"""
            **해결 단계:**
            1. [구글 클라우드 콘솔 API 페이지](https://console.developers.google.com/apis/api/firestore.googleapis.com/overview?project=rich-54943)에 접속합니다.
            2. 화면 중앙의 **'사용(Enable)'** 버튼을 클릭합니다.
            3. 활성화 후 1~2분 뒤에 이 페이지를 새로고침(F5) 하세요.
            """)
        else:
            st.error(f"Firestore 접근 오류: {e}")

# --- 레이아웃 분할 ---
col_list, col_chart = st.columns([3, 2])

with col_list:
    st.subheader("💼 내 포트폴리오")
    # (포트폴리오 리스트 로직...)
    st.info("API 활성화 전까지는 샘플 데이터가 표시되거나 비어있을 수 있습니다.")

with col_chart:
    st.subheader("🔍 종목 심층 분석")
    analysis_name = st.text_input("종목명 또는 티커 입력", value="삼성전자")
    analysis_ticker = get_ticker_from_name(analysis_name)
    
    st.write(f"**현재 분석 티커:** `{analysis_ticker}`")
    
    st.markdown("---")
    st.write("📊 **펀더멘털 & 벨류에이션**")
    
    with st.spinner("야후 파이낸스에서 데이터를 수집 중..."):
        info = get_info_data(analysis_ticker)
        
    if info:
        f1, f2 = st.columns(2)
        m_cap = info['marketCap'] / 10**8 if info['marketCap'] > 0 else 0
        
        def format_val(val, suffix="", is_pct=False):
            if val == 0 or val is None: return "-"
            if is_pct: return f"{val*100:.2f}%"
            return f"{val:,.2f}{suffix}"

        f1.metric("시가총액", f"{m_cap:,.0f} 억" if m_cap > 0 else "-")
        f1.metric("PER (Fwd)", format_val(info['forwardPE']))
        f1.metric("PBR", format_val(info['priceToBook']))
        
        f2.metric("배당수익률", format_val(info['dividendYield'], is_pct=True))
        f2.metric("ROE", format_val(info['returnOnEquity'], is_pct=True))
        f2.metric("PER (Trail)", format_val(info['trailingPE']))
        
        with st.expander("📝 기업 개요"):
            st.write(info['longBusinessSummary'])
    else:
        st.error(f"'{analysis_ticker}' 데이터를 가져올 수 없습니다. 티커를 확인해 주세요.")
