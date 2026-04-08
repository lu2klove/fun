import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account
import json
import re

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📈",
    layout="wide"
)

# --- 2. Firestore 데이터베이스 초기화 및 인증 ---
@st.cache_resource
def init_db():
    try:
        if "firebase" in st.secrets:
            if "text_key" in st.secrets["firebase"]:
                raw_json = st.secrets["firebase"]["text_key"]
                processed_json = raw_json.replace("\\\\n", "\n").replace("\\n", "\n")
                
                try:
                    key_dict = json.loads(processed_json, strict=False)
                except json.JSONDecodeError:
                    cleaned_json = processed_json.replace('\n', '\\n').replace('\r', '\\r')
                    key_dict = json.loads(cleaned_json, strict=False)
                
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n").strip()
                
                creds = service_account.Credentials.from_service_account_info(key_dict)
                
                # [수정] database ID를 사용자가 설정한 'richfin'으로 변경합니다.
                client = firestore.Client(
                    credentials=creds, 
                    project=key_dict.get('project_id'),
                    database="richfin"
                )
                return client
        st.error("Secrets 설정에서 'firebase' 정보를 찾을 수 없습니다.")
        return None
    except Exception as e:
        st.error(f"인증 오류 발생: {e}")
        return None

# DB 초기화
db = init_db()
COLLECTION_NAME = "my_portfolio"

# --- 3. DB 핸들링 함수 ---
def get_portfolio_from_db():
    if db is None:
        return []
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        results = [{"id": d.id, **d.to_dict()} for d in docs]
        results.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        return results
    except Exception as e:
        error_msg = str(e)
        # DB ID가 틀렸거나 아직 생성 중일 때 발생하는 오류 처리
        if "404" in error_msg or "not exist" in error_msg.lower():
            st.error(f"🚨 **데이터베이스 'richfin'을 찾을 수 없습니다.**")
            st.markdown(f"""
            1. **ID 확인**: Firestore 콘솔에서 데이터베이스 ID가 정확히 `richfin`인지 확인하세요.
            2. **캐시 삭제**: 사이드바의 **[DB 연결 초기화]** 버튼을 클릭하세요.
            """)
        else:
            st.warning(f"데이터 로드 오류: {e}")
        return []

def add_to_portfolio(name, ticker, buy_price, quantity):
    if db is None:
        st.error("데이터베이스 연결 실패")
        return False
    try:
        db.collection(COLLECTION_NAME).add({
            "name": name, 
            "ticker": ticker, 
            "buy_price": float(buy_price), 
            "quantity": int(quantity), 
            "created_at": datetime.now()
        })
        return True
    except Exception as e:
        st.error(f"데이터 저장 오류: {e}")
        return False

def delete_from_portfolio(doc_id):
    if db:
        try:
            db.collection(COLLECTION_NAME).document(doc_id).delete()
            return True
        except Exception as e:
            st.error(f"삭제 오류: {e}")
            return False
    return False

# --- 4. 데이터 수집 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        yt = yf.Ticker(ticker)
        data = yt.history(period="1d")
        if not data.empty:
            price = data['Close'].iloc[-1]
            prev_price = data['Open'].iloc[-1]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return price, change, change_pct
    except Exception:
        return 0.0, 0.0, 0.0

# --- 5. 티커 맵핑 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "네이버": "035420.KS",
    "카카오": "035720.KS", "현대차": "005380.KS", "애플": "AAPL", "테슬라": "TSLA",
    "엔비디아": "NVDA", "비트코인": "BTC-USD"
}

def get_ticker_from_name(name):
    clean = name.strip().replace(" ", "")
    return COMPANY_TICKER_MAP.get(clean, clean.upper())

# --- 6. UI 구성 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
st.caption(f"DB 모드: richfin | 업데이트: {datetime.now().strftime('%H:%M:%S')}")

# 증시 지표
col1, col2 = st.columns(2)
with col1:
    p, _, pct = get_finance_data("^KS11")
    st.metric("KOSPI", f"{p:,.2f}", f"{pct:+.2f}%")
with col2:
    p, _, pct = get_finance_data("^IXIC")
    st.metric("NASDAQ", f"{p:,.2f}", f"{pct:+.2f}%")

st.divider()

# 포트폴리오
st.subheader("💼 내 보유 종목")
with st.expander("➕ 종목 추가"):
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    in_name = c1.text_input("종목명")
    in_buy = c2.number_input("평단가", min_value=0.0)
    in_qty = c3.number_input("수량", min_value=0)
    if c4.button("등록"):
        if in_name and in_buy > 0:
            ticker = get_ticker_from_name(in_name)
            if add_to_portfolio(in_name, ticker, in_buy, in_qty):
                st.success("등록되었습니다.")
                st.rerun()

portfolio = get_portfolio_from_db()
if portfolio:
    df_list = []
    for item in portfolio:
        curr, _, _ = get_finance_data(item['ticker'])
        gain = (curr - item['buy_price']) * item['quantity']
        df_list.append({
            "종목": item['name'],
            "현재가": f"{curr:,.0f}",
            "수익금": f"{gain:,.0f}",
            "ID": item['id']
        })
    st.table(pd.DataFrame(df_list).drop(columns="ID"))
else:
    st.info("현재 등록된 종목이 없거나 데이터를 불러오는 중입니다.")

# 사이드바
st.sidebar.title("관리")
if st.sidebar.button("♻️ DB 연결 초기화"):
    st.cache_resource.clear()
    st.rerun()

if db:
    st.sidebar.success("✅ richfin DB 연결됨")
else:
    st.sidebar.error("❌ DB 연결 안 됨")
