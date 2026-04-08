import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📈",
    layout="wide"
)

# --- 타이틀 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
st.caption(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- 회사명-티커 변환 맵핑 사전 ---
COMPANY_TICKER_MAP = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KS",
    "현대차": "005380.KS",
    "LG에너지솔루션": "373220.KS",
    "애플": "AAPL",
    "테슬라": "TSLA",
    "엔비디아": "NVDA",
    "마이크로소프트": "MSFT",
    "구글": "GOOGL",
    "아마존": "AMZN",
    "넷플릭스": "NFLX",
    "메타": "META",
    "비트코인": "BTC-USD"
}

# --- 데이터 가져오기 함수 ---
@st.cache_data(ttl=60)
def get_finance_data(ticker):
    try:
        yt = yf.Ticker(ticker)
        # 1d 데이터가 없을 경우를 대비해 5d 데이터를 가져와 마지막 종가 사용
        data = yt.history(period="5d")
        if not data.empty:
            price = data['Close'].iloc[-1]
            prev_price = data['Close'].iloc[-2] if len(data) > 1 else data['Open'].iloc[-1]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return price, change, change_pct
        return 0.0, 0.0, 0.0
    except Exception:
        return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_chart_data(ticker, name, period="1mo"):
    try:
        yt = yf.Ticker(ticker)
        interval = "15m" if period == "1d" else "1d"
        data = yt.history(period=period, interval=interval)

        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
            if period == "1d":
                df.index = df.index.strftime('%H:%M')
            else:
                df.index = df.index.strftime('%Y-%m-%d')
            return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def get_ticker_from_name(name):
    clean_name = name.strip().replace(" ", "")
    if clean_name in COMPANY_TICKER_MAP:
        return COMPANY_TICKER_MAP[clean_name]
    return clean_name.upper()

# --- 화면 구성 ---

# 1. 상단: 국내/미국 증시 비교
col_left, col_right = st.columns(2)
period_map = {"1일": "1d", "1개월": "1mo", "1년": "1y"}

with col_left:
    st.subheader("🇰🇷 국내 증시 흐름")
    k_period = st.radio("기간 (국내)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="k_p")
    selected_k_period = period_map[k_period]

    k_col1, k_col2 = st.columns(2)
    kp_price, _, kp_pct = get_finance_data("^KS11")
    kd_price, _, kd_pct = get_finance_data("^KQ11")

    k_col1.metric("KOSPI", f"{kp_price:,.2f}", f"{kp_pct:+.2f}%")
    k_col2.metric("KOSDAQ", f"{kd_price:,.2f}", f"{kd_pct:+.2f}%")

    kp_df = get_chart_data("^KS11", "KOSPI", period=selected_k_period)
    kd_df = get_chart_data("^KQ11", "KOSDAQ", period=selected_k_period)

    if not kp_df.empty:
        st.line_chart(pd.concat([kp_df, kd_df], axis=1), height=250)

with col_right:
    st.subheader("🇺🇸 미국 증시 흐름")
    u_period = st.radio("기간 (미국)", ["1일", "1개월", "1년"], index=1, horizontal=True, key="u_p")
    selected_u_period = period_map[u_period]

    u_col1, u_col2 = st.columns(2)
    sp_price, _, sp_pct = get_finance_data("^GSPC")
    nas_price, _, nas_pct = get_finance_data("^IXIC")

    u_col
