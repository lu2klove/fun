import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import requests

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard V1.3",
    page_icon="📈",
    layout="wide"
)

# --- 2. Firestore 데이터베이스 초기화 ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            # secrets.toml 설정 방식에 따른 유연한 처리
            if "text_key" in st.secrets["firebase"]:
                raw_json = st.secrets["firebase"]["text_key"]
                key_dict = json.loads(raw_json.replace("\\n", "\n"))
            else:
                # 개별 필드로 입력된 경우
                key_dict = {
                    "project_id": st.secrets["firebase"]["project_id"],
                    "private_key": st.secrets["firebase"]["private_key"].replace("\\n", "\n"),
                    "client_email": st.secrets["firebase"]["client_email"],
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "type": "service_account"
                }
            
            creds = service_account.Credentials.from_service_account_info(key_dict)
            client = firestore.Client(credentials=creds, project=key_dict.get('project_id'))
            return client
        return None
    except Exception as e:
        st.error(f"DB 연결 인증 오류: {e}")
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. 데이터 수집 함수 (강화됨) ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        if not ticker: return 0.0, 0.0, 0.0
        yt = yf.Ticker(ticker)
        data = yt.history(period="5d")
        if not data.empty and len(data) >= 1:
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
    """국내 종목 및 해외 종목의 info 필드 차이를 고려한 안전한 데이터 추출"""
    try:
        if not ticker: return None
        yt = yf.Ticker(ticker)
        info = yt.info
        
        # 한국 종목은 marketCap이 다른 이름이거나 없을 수 있음
        # 기본값 0으로 설정하여 에러 방지
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

# 에러 메시지 가이드 (Firestore API 미활성화 대응)
if db is None:
    st.warning("⚠️ Firestore 연결이 설정되지 않았습니다. 'secrets.toml' 설정을 확인하세요.")
else:
    try:
        # 간단한 연결 테스트
        db.collection(COLLECTION_NAME).limit(1).get()
    except Exception as e:
        if "403" in str(e) or "disabled" in str(e).lower():
            st.error("🚨 **Firestore API가 비활성화되어 있습니다.**")
            st.markdown(f"""
            **해결 방법:**
            1. [Google Cloud Console](https://console.developers.google.com/apis/api/firestore.googleapis.com/overview?project=rich-54943)에 접속합니다.
            2. **'사용(Enable)'** 버튼을 클릭합니다.
            3. 약 2~3분 후 페이지를 새로고침하세요.
            """)
        else:
            st.error(f"DB 오류: {e}")

# --- 포트폴리오 및 분석 화면 (기존 로직 유지하되 info 출력 강화) ---
col_list, col_chart = st.columns([3, 2])

with col_list:
    st.subheader("💼 내 포트폴리오")
    # ... (데이터 리스트 출력 부분은 생략/기존 유지) ...
    st.info("Firestore API를 활성화하면 여기에 데이터가 표시됩니다.")

with col_chart:
    st.subheader("🔍 종목 심층 분석")
    analysis_name = st.text_input("분석할 종목명 또는 티커", value="삼성전자")
    analysis_ticker = get_ticker_from_name(analysis_name)
    
    st.write(f"**분석 중인 티커:** `{analysis_ticker}`")
    
    # 펀더멘털 섹션
    st.markdown("---")
    st.write("📊 **펀더멘털 & 벨류에이션**")
    
    with st.spinner("데이터를 불러오는 중..."):
        info = get_info_data(analysis_ticker)
        
    if info:
        f1, f2 = st.columns(2)
        m_cap = info['marketCap'] / 10**8 if info['marketCap'] > 0 else 0
        
        # 값이 0인 경우 'N/A' 또는 '-'로 표시하여 가독성 증대
        def format_val(val, suffix="", is_pct=False):
            if val == 0: return "-"
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
        st.error(f"'{analysis_ticker}' 종목 정보를 Yahoo Finance에서 찾을 수 없습니다.")
