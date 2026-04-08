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
    page_title="Global Financial Dashboard V1.6",
    page_icon="📈",
    layout="wide"
)

# --- 2. Firestore 초기화 (1.1 버전의 안정적인 방식 복구) ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            # 1.1 버전에서 사용하던 가장 단순하고 확실한 로직으로 회귀
            raw_json = st.secrets["firebase"]["text_key"]
            key_dict = json.loads(raw_json.replace("\\n", "\n"))
            
            creds = service_account.Credentials.from_service_account_info(key_dict)
            # database 인자를 제거하여 기본 설정(default)을 따르도록 수정
            client = firestore.Client(credentials=creds, project=key_dict.get('project_id'))
            return client
        return None
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return None

db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. 데이터 수집 함수 (안정성 강화) ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        if not ticker: return 0.0, 0.0, 0.0
        yt = yf.Ticker(ticker)
        # period를 1mo로 늘려 데이터 누락 방지
        data = yt.history(period="1mo")
        if not data.empty:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2] if len(data) >= 2 else price
            change = price - prev_price
            change_pct = (change / prev_price * 100) if prev_price != 0 else 0
            return float(price), float(change), float(change_pct)
    except:
        pass
    return 0.0, 0.0, 0.0

@st.cache_data(ttl=3600)
def get_info_data(ticker):
    """삼성전자 등 국내 종목 데이터 누락 시 기본값 반환"""
    try:
        if not ticker: return None
        yt = yf.Ticker(ticker)
        info = yt.info
        
        # 필드가 비어있을 경우를 대비한 딕셔너리 구성
        return {
            "marketCap": info.get('marketCap') or info.get('totalAssets') or 0,
            "forwardPE": info.get('forwardPE') or info.get('trailingPE') or 0,
            "trailingPE": info.get('trailingPE') or 0,
            "priceToBook": info.get('priceToBook') or 0,
            "dividendYield": info.get('dividendYield') or 0,
            "returnOnEquity": info.get('returnOnEquity') or 0,
            "longBusinessSummary": info.get('longBusinessSummary') or info.get('shortName') or '상세 정보 없음'
        }
    except:
        return None

# --- 4. 티커 변환 로직 (자동 검색 기능 유지) ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA"
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
    # 영문 대문자 위주면 티커로 간주
    if clean.replace(".","").isalnum() and clean.upper() == clean: return clean
    # 검색 시도
    found = search_ticker(clean)
    return found if found else clean.upper()

# --- 5. UI 구성 ---
st.title("📊 글로벌 경제 통합 대시보드 V1.6")

if db is None:
    st.error("❌ Firestore 연결에 실패했습니다. Secrets 설정을 확인하세요.")
else:
    # --- 상단 지표 ---
    indices = [("^KS11", "KOSPI"), ("^IXIC", "NASDAQ"), ("KRW=X", "환율")]
    idx_cols = st.columns(len(indices))
    for i, (t, n) in enumerate(indices):
        p, _, pct = get_finance_data(t)
        idx_cols[i].metric(n, f"{p:,.2f}", f"{pct:+.2f}%")

    st.divider()

    col_list, col_chart = st.columns([3, 2])

    with col_list:
        st.subheader("💼 포트폴리오 관리")
        # 등록 폼 (기존 기능 유지)
        with st.expander("➕ 종목 추가"):
            in_name = st.text_input("종목명 (예: 삼성전자)")
            in_buy = st.number_input("평단가", min_value=0.0)
            in_qty = st.number_input("수량", min_value=0)
            if st.button("등록"):
                ticker = get_ticker_from_name(in_name)
                db.collection(COLLECTION_NAME).add({
                    "name": in_name, "ticker": ticker, "buy_price": in_buy, "quantity": in_qty,
                    "created_at": datetime.now()
                })
                st.rerun()

        # 데이터 출력
        docs = db.collection(COLLECTION_NAME).order_by("created_at", direction="DESCENDING").stream()
        items = []
        for d in docs:
            v = d.to_dict()
            p, _, _ = get_finance_data(v['ticker'])
            gain = (p - v['buy_price']) * v['quantity']
            items.append({
                "종목": v['name'], "티커": v['ticker'], "현재가": p, 
                "평단가": v['buy_price'], "수익금": gain
            })
        
        if items:
            st.table(pd.DataFrame(items))

    with col_chart:
        st.subheader("🔍 종목 상세 분석")
        analysis_name = st.text_input("분석 종목", value="삼성전자")
        analysis_ticker = get_ticker_from_name(analysis_name)
        st.caption(f"분석 티커: {analysis_ticker}")

        info = get_info_data(analysis_ticker)
        if info:
            st.metric("시가총액", f"{info['marketCap']/10**8:,.0f} 억" if info['marketCap'] else "-")
            st.write(f"**PBR:** {info['priceToBook']:.2f}")
            with st.expander("기업 개요"):
                st.write(info['longBusinessSummary'])
