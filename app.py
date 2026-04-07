import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 페이지 설정 ---
st.set_page_config(
    page_title="Global Financial Dashboard",
    page_icon="📈",
    layout="wide" # 화면을 넓게 사용하기 위해 wide 모드 설정
)

# --- 타이틀 ---
st.title("📊 실시간 글로벌 경제 지표 대시보드")
# 현재 일시 기준 업데이트 표시
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
        data = yt.history(period="1d")
        if not data.empty:
            price = data['Close'].iloc[-1]
            prev_price = data['Open'].iloc[-1]
            change = price - prev_price
            change_pct = (change / prev_price) * 100
            return price, change, change_pct
    except Exception:
        return 0.0, 0.0, 0.0

@st.cache_data(ttl=300)
def get_chart_data(ticker, name):
    try:
        yt = yf.Ticker(ticker)
        data = yt.history(period="1mo")
        if not data.empty:
            df = data[['Close']].copy()
            df.columns = [name]
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

# 1. 상단: 좌우 분할 (국내 vs 미국)
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🇰🇷 국내 증시 흐름 비교")
    k_col1, k_col2 = st.columns(2)
    
    # 지수 데이터 가져오기
    kp_price, kp_chg, kp_pct = get_finance_data("^KS11")
    kd_price, kd_chg, kd_pct = get_finance_data("^KQ11")
    
    k_col1.metric("KOSPI", f"{kp_price:,.2f}", f"{kp_pct:+.2f}%")
    k_col2.metric("KOSDAQ", f"{kd_price:,.2f}", f"{kd_pct:+.2f}%")
    
    # 국내 증시 통합 차트 생성
    kp_df = get_chart_data("^KS11", "KOSPI")
    kd_df = get_chart_data("^KQ11", "KOSDAQ")
    
    if not kp_df.empty and not kd_df.empty:
        # 두 데이터를 합쳐서 하나의 차트로 표시
        k_combined = pd.concat([kp_df, kd_df], axis=1)
        # 컬럼 순서를 고정하고 리스트 형태로 색상 전달 (KOSPI=파랑, KOSDAQ=빨강)
        k_combined = k_combined[["KOSPI", "KOSDAQ"]]
        st.line_chart(k_combined, color=["#0000FF", "#FF0000"])

with col_right:
    st.subheader("🇺🇸 미국 증시 흐름 비교")
    u_col1, u_col2 = st.columns(2)
    
    # 지수 데이터 가져오기
    sp_price, sp_chg, sp_pct = get_finance_data("^GSPC")
    nas_price, nas_chg, nas_pct = get_finance_data("^IXIC")
    
    u_col1.metric("S&P 500", f"{sp_price:,.2f}", f"{sp_pct:+.2f}%")
    u_col2.metric("NASDAQ", f"{nas_price:,.2f}", f"{nas_pct:+.2f}%")
    
    # 미국 증시 통합 차트 생성
    sp_df = get_chart_data("^GSPC", "S&P 500")
    nas_df = get_chart_data("^IXIC", "NASDAQ")
    
    if not sp_df.empty and not nas_df.empty:
        # 두 데이터를 합쳐서 하나의 차트로 표시
        u_combined = pd.concat([sp_df, nas_df], axis=1)
        # 컬럼 순서를 고정하고 리스트 형태로 색상 전달 (NASDAQ=파랑, S&P 500=빨강)
        u_combined = u_combined[["NASDAQ", "S&P 500"]]
        st.line_chart(u_combined, color=["#0000FF", "#FF0000"])

st.divider()

# 2. 중간: 3분할 (환율, 유가, 원자재)
st.subheader("🌐 주요 경제 지표 분석")
col_bot1, col_bot2, col_bot3 = st.columns(3)

with col_bot1:
    st.write("💱 **환율 (USD/KRW)**")
    fx_price, fx_chg, fx_pct = get_finance_data("KRW=X")
    st.metric("원/달러 환율", f"{fx_price:,.2f}원", f"{fx_chg:+.2f}")
    if fx_price <= 1500:
        st.success("✅ 정상 (1,500원 이하 유지 중)")
    else:
        st.error("⚠️ 주의 (1,500원 초과 상태)")

with col_bot2:
    st.write("🛢️ **에너지 (WTI Crude Oil)**")
    oil_price, oil_chg, oil_pct = get_finance_data("CL=F")
    st.metric("WTI 유가", f"${oil_price:,.2f}", f"{oil_pct:+.2f}%")
    if oil_price <= 100:
        st.success("✅ 정상 ($100 이하 유지 중)")
    else:
        st.error("⚠️ 주의 ($100 초과 상태)")

with col_bot3:
    st.write("🔋 **원자재 (Lithium)**")
    lit_price, lit_chg, lit_pct = get_finance_data("LIT")
    st.metric("Global Lithium (LIT)", f"${lit_price:,.2f}", f"{lit_pct:+.2f}%")

st.divider()

# 3. 하단: 관심 종목 시세 및 차트
st.subheader("⭐ 관심 종목 분석")
st.info("조회하고 싶은 **회사명** 또는 **티커**를 입력하세요. (예: 삼성전자, 테슬라, 애플)")

input_cols = st.columns(5)
watchlist_data = []

for i in range(5):
    name_input = input_cols[i].text_input(f"종목 {i+1}", key=f"ticker_{i}")
    if name_input:
        ticker = get_ticker_from_name(name_input)
        watchlist_data.append({"name": name_input, "ticker": ticker})

if watchlist_data:
    display_cols = st.columns(len(watchlist_data))
    for i, item in enumerate(watchlist_data):
        with display_cols[i]:
            price, chg, pct = get_finance_data(item["ticker"])
            if price != 0:
                st.metric(f"{item['name']} ({item['ticker']})", f"{price:,.2f}", f"{pct:+.2f}%")
                # 종목별 단독 차트
                chart_data = get_chart_data(item["ticker"], item["name"])
                if not chart_data.empty:
                    st.line_chart(chart_data, height=150)
                else:
                    st.warning("차트 데이터 없음")
            else:
                st.error(f"'{item['name']}' 검색 실패")
else:
    st.write("조회할 회사명이나 티커를 입력해 주세요.")

# 사이드바 설정
st.sidebar.header("Dashboard Settings")
if st.sidebar.button("새로고침"):
    st.rerun()

st.sidebar.divider()
st.sidebar.info("""
**배포 및 관리 안내:**
- 이 웹 사이트는 GitHub와 Streamlit Cloud를 통해 호스팅됩니다.
- 코드 수정 후 GitHub에 Push하면 자동으로 웹에 반영됩니다.
- 문의: [개발자 이메일 또는 관련 정보]
""")
